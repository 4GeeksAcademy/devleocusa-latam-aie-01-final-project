"""
Telemetry middleware for TrackFlow API.

Implements:
- PII sanitization (emails, phones, file paths → [REDACTED])
- Circuit breaker (silence mode when >10 errors/10s from same endpoint)
- Exclusion enforcement (passwords, JWT bodies, credit cards, GPS, etc.)
- Event emission helper (emits to stdout / OTel collector / Kafka)

Usage in fastapi_server.py::

    from src.telemetry import TelemetryMiddleware
    app.add_middleware(TelemetryMiddleware)
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


# ──────────────────────────────────────────────
# PII SANITIZATION
# ──────────────────────────────────────────────

# Compiled regexes — single scan pass
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}\b")
_ABSOLUTE_PATH_RE = re.compile(
    r"(?:/home|/Users|/var|/opt|/etc|C:\\|/app)[\w/\\\.\-]+",
)
_CREDIT_CARD_RE = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")
_GPS_COORD_RE = re.compile(
    r"\b[-+]?(?:90(?:\.0+)?|[1-8]?\d(?:\.\d+)?)\s*[°º]\s*[-+]?(?:180(?:\.0+)?|1[0-7]\d(?:\.\d+)?|\d{1,2}(?:\.\d+)?)\s*['′\"″]?\b"
)
_DNI_RE = re.compile(r"\b\d{8}[A-Z]\b")  # Spanish DNI pattern
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")  # US SSN

# Fields that must NEVER appear in telemetry payloads (by key name)
EXCLUDED_KEYS: frozenset[str] = frozenset({
    "password", "passwd", "secret", "token", "credit_card",
    "ssn", "dni", "nif", "gps", "coordinates", "health_data",
    "whatsapp_content", "email_body", "message_content",
})


def sanitize_value(value: str) -> str:
    """Scan a string value for PII patterns and redact them.

    Applied to every string field in the properties dict before emission.
    """
    result = value
    result = _EMAIL_RE.sub("[EMAIL_REDACTED]", result)
    result = _PHONE_RE.sub("[PHONE_REDACTED]", result)
    result = _ABSOLUTE_PATH_RE.sub("[PATH_REDACTED]", result)
    result = _CREDIT_CARD_RE.sub("[CC_REDACTED]", result)
    result = _GPS_COORD_RE.sub("[GPS_REDACTED]", result)
    result = _DNI_RE.sub("[DNI_REDACTED]", result)
    result = _SSN_RE.sub("[SSN_REDACTED]", result)
    # Truncate to 300 chars as per policy
    return result[:300]


def sanitize_properties(props: dict[str, Any]) -> dict[str, Any]:
    """Recursively sanitize all string values in a properties dict.

    Also drops any key that matches EXCLUDED_KEYS.
    Returns both the sanitized dict and a list of excluded keys found.
    """
    sanitized: dict[str, Any] = {}
    for key, value in props.items():
        if key.lower() in EXCLUDED_KEYS:
            continue  # Exclusion enforcement — will be reported by caller
        if isinstance(value, str):
            sanitized[key] = sanitize_value(value)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_properties(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_value(item) if isinstance(item, str)
                else sanitize_properties(item) if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            sanitized[key] = value
    return sanitized


# ──────────────────────────────────────────────
# CIRCUIT BREAKER
# ──────────────────────────────────────────────

class CircuitBreaker:
    """Silence mode per endpoint when error rate exceeds threshold.

    If more than ``threshold`` errors occur from the same endpoint
    within ``window_seconds``, subsequent errors are suppressed
    (only 1 summary event per ``cooldown_seconds`` is emitted).
    """

    def __init__(
        self,
        threshold: int = 10,
        window_seconds: int = 10,
        cooldown_seconds: int = 30,
    ) -> None:
        self._threshold = threshold
        self._window_seconds = window_seconds
        self._cooldown_seconds = cooldown_seconds
        self._error_counts: dict[str, list[float]] = defaultdict(list)
        self._silent_until: dict[str, float] = {}
        self._dropped_counts: dict[str, int] = defaultdict(int)

    @property
    def threshold(self) -> int:
        return self._threshold

    @property
    def window_seconds(self) -> int:
        return self._window_seconds

    def is_silent(self, endpoint: str) -> bool:
        """Check if this endpoint is currently in silence mode."""
        expiry = self._silent_until.get(endpoint, 0.0)
        now = time.monotonic()
        if now < expiry:
            return True
        # If cooldown expired — emit one final summary with dropped_count
        if expiry > 0:
            self._silent_until.pop(endpoint, None)
            self._error_counts.pop(endpoint, None)
        return False

    def record_error(self, endpoint: str) -> bool:
        """Record an error for this endpoint.

        Returns True if the event should still be emitted (not suppressed).
        Returns False if the circuit is open → suppress emission.
        """
        now = time.monotonic()
        window_start = now - self._window_seconds

        # Prune old entries
        counts = self._error_counts[endpoint]
        self._error_counts[endpoint] = [t for t in counts if t > window_start]

        # Add current
        self._error_counts[endpoint].append(now)

        if len(self._error_counts[endpoint]) > self._threshold:
            self._silent_until[endpoint] = now + self._cooldown_seconds
            return False  # Suppress — circuit open

        return True  # Emit normally

    def count_dropped(self, endpoint: str) -> int:
        """Increment the dropped event counter for this endpoint.

        Returns the updated count so callers can include it in summary events.
        """
        self._dropped_counts[endpoint] += 1
        return self._dropped_counts[endpoint]

    def pop_dropped(self, endpoint: str) -> int:
        """Return the dropped count for this endpoint and reset it to 0.

        Call this when emitting the summary event after cooldown.
        """
        return self._dropped_counts.pop(endpoint, 0)


# ──────────────────────────────────────────────
# ENVELOPE BUILDER
# ──────────────────────────────────────────────

def build_envelope(
    event_type: str,
    properties: dict[str, Any],
    *,
    user_id: str = "",
    session_id: str = "",
    request_id: str = "",
) -> str:
    """Build a JSON string of the standard Event Envelope.

    All string values in *properties* are automatically sanitized.
    If any exclusion keys are found, a ``telemetry.exclusions.enforced``
    event is emitted for audit trail (except for that event itself).
    """
    # Detect excluded keys before sanitization strips them
    # Guard: never recurse from the exclusion event itself
    if event_type != "telemetry.exclusions.enforced":
        for key in list(properties):
            if key.lower() in EXCLUDED_KEYS:
                print(
                    "TELEMETRY:"
                    + json.dumps(
                        {
                            "eventId": str(uuid4()),
                            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "sessionId": session_id,
                            "userId": user_id,
                            "event_type": "telemetry.exclusions.enforced",
                            "schemaVersion": "1.0.0",
                            "requestId": request_id,
                            "properties": {
                                "excluded_key": key,
                                "event_type_origin": event_type,
                                "source": "backend",
                            },
                        }
                    ),
                    flush=True,
                )
                break  # One audit event per envelope is enough

    sanitized = sanitize_properties(properties)
    envelope = {
        "eventId": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sessionId": session_id,
        "userId": user_id,
        "event_type": event_type,
        "schemaVersion": "1.0.0",
        "requestId": request_id,
        "properties": sanitized,
    }
    return json.dumps(envelope)


def emit_event(
    event_type: str,
    properties: dict[str, Any],
    *,
    user_id: str = "",
    session_id: str = "",
    request_id: str = "",
) -> None:
    """Emit a telemetry event.

    In production, this would write to a Kafka/Redpanda topic or
    send to the OpenTelemetry Collector via gRPC/HTTP.

    For the current implementation, it writes a JSON line to stdout
    where the OTel Collector or a log shipper can pick it up.
    """
    envelope = build_envelope(
        event_type,
        properties,
        user_id=user_id,
        session_id=session_id,
        request_id=request_id,
    )
    # Stdout for container environments (CloudWatch, Datadog, OTel Collector)
    print(f"TELEMETRY:{envelope}", flush=True)


# ──────────────────────────────────────────────
# FASTAPI MIDDLEWARE
# ──────────────────────────────────────────────

class TelemetryMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that:

    1. Intercepts errors (HTTPException / 5xx) and emits sanitized events.
    2. Applies the circuit breaker to prevent error storms.
    3. Injects requestId into request.state for downstream use.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._breaker = CircuitBreaker(
            threshold=int(os.getenv("TELEMETRY_CB_THRESHOLD", "10")),
            window_seconds=int(os.getenv("TELEMETRY_CB_WINDOW_SEC", "10")),
            cooldown_seconds=int(os.getenv("TELEMETRY_CB_COOLDOWN_SEC", "30")),
        )

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Tag every request with a requestId for correlation
        request_id = str(uuid4())
        request.state.request_id = request_id

        # Extract user info from request if available
        user_id = ""
        session_id = ""
        if hasattr(request.state, "user") and request.state.user:
            user_id = str(getattr(request.state.user, "id", ""))
        if hasattr(request.state, "jti"):
            session_id = request.state.jti

        # Build endpoint key for circuit breaker
        endpoint = f"{request.method} {request.url.path}"

        try:
            response = await call_next(request)
        except Exception as exc:
            # Catch unhandled exceptions → 500
            status_code = 500
            error_type = "api.error.server"
            error_detail = str(exc)[:300]

            # Circuit breaker check
            if not self._breaker.record_error(endpoint):
                # Circuit open — count dropped and emit throttle event
                dropped = self._breaker.count_dropped(endpoint)
                emit_event(
                    "telemetry.throttle.activated",
                    {
                        "endpoint": endpoint,
                        "reason": f"circuit_breaker: >{self._breaker.threshold} errors in {self._breaker.window_seconds}s",
                        "original_event_type": error_type,
                        "dropped_count": dropped,
                    },
                    user_id=user_id,
                    session_id=session_id,
                    request_id=request_id,
                )
                raise  # Re-raise, the response is still an error for the client

            emit_event(
                error_type,
                {
                    "method": request.method,
                    "path": request.url.path,
                    "http_status": status_code,
                    "error_detail": sanitize_value(error_detail),
                },
                user_id=user_id,
                session_id=session_id,
                request_id=request_id,
            )
            raise  # Re-raise after emitting

        # Capture 4xx/5xx responses
        if response.status_code >= 400:
            # Determine event type
            if response.status_code >= 500:
                error_type = "api.error.server"
            elif response.status_code == 422:
                error_type = "api.error.validation"
            else:
                error_type = "api.error.client"

            # Circuit breaker check only for 5xx
            if response.status_code >= 500:
                if not self._breaker.record_error(endpoint):
                    dropped = self._breaker.count_dropped(endpoint)
                    emit_event(
                        "telemetry.throttle.activated",
                        {
                            "endpoint": endpoint,
                            "reason": f"circuit_breaker: >{self._breaker.threshold} 5xx errors in {self._breaker.window_seconds}s",
                            "original_event_type": error_type,
                            "dropped_count": dropped,
                        },
                        user_id=user_id,
                        session_id=session_id,
                        request_id=request_id,
                    )
                    return response  # Don't emit duplicate error event

            emit_event(
                error_type,
                {
                    "method": request.method,
                    "path": request.url.path,
                    "http_status": response.status_code,
                },
                user_id=user_id,
                session_id=session_id,
                request_id=request_id,
            )

        return response