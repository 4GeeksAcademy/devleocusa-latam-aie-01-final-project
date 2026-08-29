"""Telemetry analysis functions for TrackFlow.

Pure Pandas functions that compute operational metrics from a raw
DataFrame of telemetry events.  Each function returns a list of dicts
ready for JSON serialisation — no side effects, no DB calls, no
date-range filtering.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


# ──────────────────────────────────────────────────────────────
# Helper: expand a JSONB column of dicts into a regular DataFrame
# ──────────────────────────────────────────────────────────────

def _expand_tags(series: pd.Series) -> pd.DataFrame:
    """Expand a column of dicts into a DataFrame (one column per key).

    Entries that are not dicts (e.g. ``None``) produce NaN in every
    expanded column.
    """
    return series.apply(pd.Series)


# ═══════════════════════════════════════════════════════════════
# 1. Tasa de errores por endpoint
# ═══════════════════════════════════════════════════════════════

def error_rate_by_endpoint(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Compute error rate (%) per API endpoint.

    Extracts the ``endpoint`` field from the JSON ``tags`` column and
    flags rows where ``severity == 'error'``.  Returns one row per
    endpoint with total requests, error count, average latency, and
    error rate percentage.

    Parameters
    ----------
    df : pd.DataFrame
        Raw telemetry DataFrame.  Must contain columns ``tags`` (JSONB
        as dicts), ``severity`` (str), and ``timestamp`` (str or
        datetime).

    Returns
    -------
    list[dict]
        Each dict has keys: ``endpoint``, ``total_requests``,
        ``error_count``, ``avg_latency_ms``, ``error_rate_pct``.
    """
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    # Expand JSON tags into columns
    tags_df = _expand_tags(df["tags"])
    df["_endpoint"] = tags_df.get("endpoint", pd.Series(dtype="object"))

    # Flag errors
    df["_is_error"] = df["severity"] == "error"

    # Extract latency from tags (coerce non-numeric → NaN)
    df["_latency_ms"] = pd.to_numeric(
        tags_df.get("latency_ms", pd.Series(dtype="object")),
        errors="coerce",
    )

    # Group by endpoint (keep rows even when endpoint is None)
    grouped = (
        df.groupby("_endpoint", dropna=False)
        .agg(
            total_requests=("_is_error", "count"),
            error_count=("_is_error", "sum"),
            avg_latency_ms=("_latency_ms", "mean"),
        )
        .reset_index()
    )

    grouped["error_rate_pct"] = (
        grouped["error_count"] / grouped["total_requests"] * 100
    ).round(2)

    grouped["avg_latency_ms"] = grouped["avg_latency_ms"].fillna(0).round(2)

    return (
        grouped.rename(columns={"_endpoint": "endpoint"})
        .fillna({"endpoint": "unknown"})
        .to_dict(orient="records")
    )


# ═══════════════════════════════════════════════════════════════
# 2. Latencia promedio por servicio
# ═══════════════════════════════════════════════════════════════

def avg_latency_by_service(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Compute average, min, and max latency (ms) grouped by service.

    Extracts ``service`` and ``latency_ms`` from the JSON ``tags``
    column.  Rows without a ``service`` tag are excluded.
    ``request_count`` is the total events for that service; latency
    metrics are computed only from rows that carry a numeric
    ``latency_ms`` value.

    Parameters
    ----------
    df : pd.DataFrame
        Raw telemetry DataFrame.  Must contain columns ``tags`` (JSONB
        as dicts) and ``timestamp`` (str or datetime).

    Returns
    -------
    list[dict]
        Each dict has keys: ``service``, ``request_count``,
        ``avg_latency_ms``, ``min_latency_ms``, ``max_latency_ms``.
    """
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    # Expand JSON tags
    tags_df = _expand_tags(df["tags"])
    df["_service"] = tags_df.get("service", pd.Series(dtype="object"))
    df["_latency_ms"] = pd.to_numeric(
        tags_df.get("latency_ms", pd.Series(dtype="object")),
        errors="coerce",
    )

    # Keep only rows that name a service
    service_df = df.dropna(subset=["_service"])

    grouped = (
        service_df.groupby("_service")
        .agg(
            request_count=("_latency_ms", "count"),
            events_with_latency=("_latency_ms", lambda s: s.notna().sum()),
            avg_latency_ms=("_latency_ms", "mean"),
            min_latency_ms=("_latency_ms", "min"),
            max_latency_ms=("_latency_ms", "max"),
        )
        .reset_index()
    )

    grouped["avg_latency_ms"] = grouped["avg_latency_ms"].round(2)

    # Replace request_count with actual event count
    # (count() skips NaN, we want total events per service)
    total_events = service_df.groupby("_service").size()
    grouped["request_count"] = grouped["_service"].map(total_events)

    # Fill NaN latencies for services that have no latency data at all
    grouped["avg_latency_ms"] = grouped["avg_latency_ms"].fillna(0).round(2)
    grouped["min_latency_ms"] = grouped["min_latency_ms"].fillna(0)
    grouped["max_latency_ms"] = grouped["max_latency_ms"].fillna(0)
    grouped["events_with_latency"] = grouped["events_with_latency"].astype(int)

    return (
        grouped.rename(columns={"_service": "service"})
        .to_dict(orient="records")
    )


# ═══════════════════════════════════════════════════════════════
# 3. Tasa diaria de fallos de login
# ═══════════════════════════════════════════════════════════════

def daily_login_failure_rate(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Compute daily login failure rate (%).

    Filters the DataFrame to only ``user_login_failed`` and
    ``user_login_succeeded`` events, then groups by calendar date
    to calculate: total attempts, failures, successes, and
    failure rate percentage.

    Parameters
    ----------
    df : pd.DataFrame
        Raw telemetry DataFrame.  Must contain columns ``event_type``
        (str), ``timestamp`` (str or datetime).

    Returns
    -------
    list[dict]
        Each dict has keys: ``date``, ``total_attempts``,
        ``failure_count``, ``success_count``, ``failure_rate_pct``.
    """
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    # Filter only login-related events
    login_mask = df["event_type"].isin(
        ["user_login_failed", "user_login_succeeded"]
    )
    login_df = df.loc[login_mask].copy()

    # Extract calendar date (date object, no time component)
    login_df["_date"] = login_df["timestamp"].dt.date

    # Flag: True for failures, False for successes
    login_df["_is_failure"] = login_df["event_type"] == "user_login_failed"

    grouped = (
        login_df.groupby("_date")
        .agg(
            total_attempts=("_is_failure", "count"),
            failure_count=("_is_failure", "sum"),
        )
        .reset_index()
    )

    # Derive success count and rate via vectorised arithmetic
    grouped["success_count"] = (
        grouped["total_attempts"] - grouped["failure_count"]
    )
    grouped["failure_rate_pct"] = (
        grouped["failure_count"] / grouped["total_attempts"] * 100
    ).round(2)

    # Convert date objects to ISO strings for JSON serialisation
    grouped["date"] = grouped["_date"].apply(lambda d: d.isoformat())

    return (
        grouped[["date", "total_attempts", "failure_count", "success_count", "failure_rate_pct"]]
        .to_dict(orient="records")
    )


# ═══════════════════════════════════════════════════════════════
# 4. Eventos por día
# ═══════════════════════════════════════════════════════════════

def events_per_day(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Aggregate event count per calendar day.

    Parameters
    ----------
    df : pd.DataFrame
        Raw telemetry DataFrame.  Must contain column ``timestamp``
        (str or datetime).

    Returns
    -------
    list[dict]
        Each dict has keys: ``date`` (ISO date string) and ``count``.
        Sorted chronologically.
    """
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    day_df = df.copy()
    day_df["_date"] = day_df["timestamp"].dt.date

    grouped = (
        day_df.groupby("_date")
        .agg(count=("_date", "count"))
        .reset_index()
    )

    _date_col = grouped["_date"]
    grouped["date"] = _date_col.apply(lambda d: d.isoformat())

    return grouped[["date", "count"]].to_dict(orient="records")


# ═══════════════════════════════════════════════════════════════
# 5. Tasa de errores por tipo de evento
# ═══════════════════════════════════════════════════════════════

def error_rate_by_type(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Compute error rate (%) per ``event_type``.

    Flags rows where ``severity == 'error'`` and groups by
    ``event_type`` to return total occurrences, error count,
    and error rate percentage.

    Parameters
    ----------
    df : pd.DataFrame
        Raw telemetry DataFrame.  Must contain columns ``event_type``
        (str), ``severity`` (str), and ``timestamp`` (str or datetime).

    Returns
    -------
    list[dict]
        Each dict has keys: ``event_type``, ``total``,
        ``error_count``, ``error_rate_pct``.
    """
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    df["_is_error"] = df["severity"] == "error"

    grouped = (
        df.groupby("event_type")
        .agg(
            total=("_is_error", "count"),
            error_count=("_is_error", "sum"),
        )
        .reset_index()
    )

    grouped["error_rate_pct"] = (
        grouped["error_count"] / grouped["total"] * 100
    ).round(2)

    return grouped.to_dict(orient="records")