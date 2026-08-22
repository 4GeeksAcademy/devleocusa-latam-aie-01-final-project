/**
 * Telemetry client for TrackFlow frontend (Next.js).
 *
 * Implements:
 * - Event Envelope builder (matches backend schema)
 * - PII sanitization in the browser before emission
 * - Debounce for ui.page.view (500ms window)
 * - Throttle for sku.list.requested (cache-aware, 30s TTL guard)
 * - Error aggregation for ui.form.validation_error (5min window)
 * - Exclusion enforcement (no passwords, JWT, GPS, etc.)
 *
 * Usage:
 *   import { emitEvent } from "@/lib/telemetry";
 *   emitEvent("ui.page.view", { page: "/backoffice/inventory" });
 */

// ─── Types ──────────────────────────────────────────────────────────────

export interface TelemetryEnvelope {
  eventId: string;
  timestamp: string;
  sessionId: string;
  userId: string;
  event_type: string;
  schemaVersion: string;
  requestId: string;
  properties: Record<string, unknown>;
}

export type EventType =
  // Obligatorio
  | "auth.login.attempt"
  | "auth.login.success"
  | "sku.create.attempt"
  | "sku.create.success"
  | "sku.create.failure"
  | "inbound.order.created"
  | "outbound.order.created"
  | "outbound.order.rejected"
  | "stock.validation.discrepancy"
  | "ui.action.error"
  | "api.error.server"
  // Oportunidad
  | "auth.login.failure"
  | "auth.password_reset.requested"
  | "auth.password_reset.completed"
  | "auth.session.expired"
  | "auth.register.completed"
  | "sku.list.requested"
  | "api.error.client"
  | "api.error.validation"
  | "performance.api.latency"
  | "cache.inventory.hit"
  | "cache.inventory.miss"
  | "incident.created"
  | "incident.resolution_time"
  | "incident.status_changed"
  | "carrier.assigned"
  | "supplier.contacted"
  | "ui.page.view"
  | "ui.form.validation_error"
  | "candidate.stage.changed"
  | "lead.conversion.rate"
  | "telemetry.throttle.activated"
  | "telemetry.exclusions.enforced"
  | "warehouse.stock_alert";

// ─── Configuration ──────────────────────────────────────────────────────

const CONFIG = {
  /** Events are sent as JSON lines to this endpoint (OTel Collector / log shipper) */
  TELEMETRY_ENDPOINT: "/api/telemetry/ingest",
  /** Debounce window for route changes (ms) */
  PAGE_VIEW_DEBOUNCE_MS: 500,
  /** Aggregation window for form validation errors (ms) */
  FORM_ERROR_WINDOW_MS: 5 * 60 * 1000, // 5 min
  /** Sample rate for performance metrics (0.1 = 10%) */
  PERFORMANCE_SAMPLE_RATE: 0.1,
};

// ─── Session / user helpers ────────────────────────────────────────────

/** Must match AUTH_TOKEN_STORAGE_KEY in services/authApi.ts */
const AUTH_TOKEN_STORAGE_KEY = "trackflow_token";

function getSessionId(): string {
  if (typeof window === "undefined") return "";
  // The JWT 'jti' claim — extracted from stored token
  try {
    const token = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
    if (!token) return "";
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.jti || payload.sub || "";
  } catch {
    return "";
  }
}

function getUserId(): string {
  if (typeof window === "undefined") return "";
  try {
    const token = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
    if (!token) return "";
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.sub || "";
  } catch {
    return "";
  }
}

function generateUUID(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  // Fallback for older browsers
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// ─── PII SANITIZATION (client-side) ────────────────────────────────────

/** Regex patterns for PII redaction in browser */
const EMAIL_RE = /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g;
const PHONE_RE = /\b\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}\b/g;
const CREDIT_CARD_RE = /\b(?:\d{4}[-\s]?){3}\d{4}\b/g;

/** Keys that are NEVER allowed in telemetry payloads */
const EXCLUDED_KEYS = new Set([
  "password", "passwd", "secret", "token", "credit_card",
  "ssn", "dni", "nif", "gps", "coordinates", "health_data",
  "whatsapp_content", "email_body", "message_content",
  "jwt", "access_token", "refresh_token",
]);

function sanitizeString(value: string): string {
  return value
    .replace(EMAIL_RE, "[EMAIL_REDACTED]")
    .replace(PHONE_RE, "[PHONE_REDACTED]")
    .replace(CREDIT_CARD_RE, "[CC_REDACTED]")
    .slice(0, 300); // Truncate to 300 chars as per policy
}

function sanitizeProps(props: Record<string, unknown>): Record<string, unknown> {
  const clean: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    if (EXCLUDED_KEYS.has(key.toLowerCase())) continue;
    if (typeof value === "string") {
      clean[key] = sanitizeString(value);
    } else if (typeof value === "object" && value !== null) {
      clean[key] = sanitizeProps(value as Record<string, unknown>);
    } else {
      clean[key] = value;
    }
  }
  return clean;
}

// ─── ENVELOPE BUILDER ──────────────────────────────────────────────────

function buildEnvelope(
  eventType: EventType | string,
  properties: Record<string, unknown>,
): TelemetryEnvelope {
  // Detect excluded keys before sanitization strips them
  // Guard: never recurse from the exclusion event itself
  if (eventType !== "telemetry.exclusions.enforced") {
    for (const key of Object.keys(properties)) {
      if (EXCLUDED_KEYS.has(key.toLowerCase())) {
        // Emit audit event inline (no recursion since we guard)
        const exclusionEnvelope: TelemetryEnvelope = {
          eventId: generateUUID(),
          timestamp: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
          sessionId: getSessionId(),
          userId: getUserId(),
          event_type: "telemetry.exclusions.enforced",
          schemaVersion: "1.0.0",
          requestId: "",
          properties: {
            excluded_key: key,
            event_type_origin: eventType,
            source: "frontend",
          },
        };
        sendEnvelope(exclusionEnvelope);
        break; // One audit event per envelope is enough
      }
    }
  }

  return {
    eventId: generateUUID(),
    timestamp: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
    sessionId: getSessionId(),
    userId: getUserId(),
    event_type: eventType,
    schemaVersion: "1.0.0",
    requestId: "",
    properties: sanitizeProps(properties),
  };
}

// ─── EMITTER ───────────────────────────────────────────────────────────

function sendEnvelope(envelope: TelemetryEnvelope): void {
  // In production, use `navigator.sendBeacon()` for reliability on page unload
  // and `fetch` for regular events.
  if (typeof navigator !== "undefined" && navigator.sendBeacon) {
    const blob = new Blob([JSON.stringify(envelope) + "\n"], {
      type: "application/json",
    });
    navigator.sendBeacon(CONFIG.TELEMETRY_ENDPOINT, blob);
  } else {
    fetch(CONFIG.TELEMETRY_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(envelope),
      // Fire-and-forget — we don't care about the response
      keepalive: true,
    }).catch(() => {
      // Silently fail — telemetry should never block the app
    });
  }
}

// ─── DEBOUNCE FOR ui.page.view ───────────────────────────────────────

let _debounceTimer: ReturnType<typeof setTimeout> | null = null;
let _lastEmittedPage: string | null = null;

function debouncedPageView(page: string, referrer: string): void {
  if (_debounceTimer) clearTimeout(_debounceTimer);
  if (page === _lastEmittedPage) return;

  _debounceTimer = setTimeout(() => {
    emitEvent("ui.page.view", { page, referrer });
    _lastEmittedPage = page;
  }, CONFIG.PAGE_VIEW_DEBOUNCE_MS);
}

// ─── THROTTLE FOR sku.list.requested (cache-aware) ────────────────────

let _lastSkuListEmit: number = 0;

function throttledSkuListRequest(totalSkus: number, fromCache: boolean, cacheAge: number): void {
  const now = Date.now();
  // If response came from cache AND cache age < 30s → skip event
  if (fromCache && cacheAge < 30000) return;

  // If last emit was < 30s ago → skip
  if (now - _lastSkuListEmit < 30000) return;

  _lastSkuListEmit = now;
  emitEvent("sku.list.requested", { total_skus: totalSkus, from_cache: fromCache });
}

// ─── AGGREGATION FOR ui.form.validation_error ─────────────────────────

interface FormErrorBucket {
  count: number;
  fields: Set<string>;
  timer: ReturnType<typeof setTimeout> | null;
}

const _formErrorBuckets = new Map<string, FormErrorBucket>();

function aggregatedFormError(formId: string, field: string, message: string): void {
  const key = formId;
  let bucket = _formErrorBuckets.get(key);

  if (!bucket) {
    bucket = { count: 0, fields: new Set(), timer: null };
    _formErrorBuckets.set(key, bucket);
  }

  bucket.count += 1;
  bucket.fields.add(field);

  // Reset / extend timer
  if (bucket.timer) clearTimeout(bucket.timer);
  bucket.timer = setTimeout(() => {
    emitEvent("ui.form.validation_error", {
      form_id: formId,
      count: bucket.count,
      fields: Array.from(bucket.fields),
      last_message: message,
    });
    _formErrorBuckets.delete(key);
  }, CONFIG.FORM_ERROR_WINDOW_MS);
}

// ─── PERFORMANCE SAMPLING ────────────────────────────────────────────

function sampledApiLatency(
  method: string,
  path: string,
  latencyMs: number,
  httpStatus: number,
): void {
  if (Math.random() > CONFIG.PERFORMANCE_SAMPLE_RATE) return;
  emitEvent("performance.api.latency", {
    method,
    path,
    latency_ms: latencyMs,
    http_status: httpStatus,
  });
}

// ─── PUBLIC API ──────────────────────────────────────────────────────

/**
 * Emit a telemetry event.
 *
 * Automatically sanitizes PII from string values and enforces
 * exclusion rules. Safe to call from any component.
 */
export function emitEvent(
  eventType: EventType | string,
  properties: Record<string, unknown>,
): void {
  const envelope = buildEnvelope(eventType, properties);
  sendEnvelope(envelope);
}

/**
 * Call this on every route change (Next.js usePathname / useRouter).
 * Automatically debounces at 500ms.
 */
export function trackPageView(page: string, referrer: string = ""): void {
  debouncedPageView(page, referrer);
}

/**
 * Call when the inventory product list is fetched.
 * Respects the TTL cache throttle rule.
 */
export function trackSkuListRequest(
  totalSkus: number,
  fromCache: boolean,
  cacheAgeMs: number,
): void {
  throttledSkuListRequest(totalSkus, fromCache, cacheAgeMs);
}

/**
 * Call when a form validation error occurs (e.g. Pydantic/Zod error).
 * Aggregates errors per form in 5-minute windows.
 */
export function trackFormError(
  formId: string,
  field: string,
  message: string,
): void {
  aggregatedFormError(formId, field, message);
}

/**
 * Call in an axios/fetch interceptor to measure API latency.
 * Sampled at 10% (configurable).
 */
export function trackApiLatency(
  method: string,
  path: string,
  latencyMs: number,
  httpStatus: number,
): void {
  sampledApiLatency(method, path, latencyMs, httpStatus);
}

/**
 * Call in the AuthGuard component when token is expired/detected.
 */
export function trackSessionExpired(sessionDurationMinutes: number): void {
  emitEvent("auth.session.expired", {
    session_duration_minutes: sessionDurationMinutes,
  });
}