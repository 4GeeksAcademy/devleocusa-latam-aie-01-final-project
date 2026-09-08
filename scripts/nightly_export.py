#!/usr/bin/env python3
"""Nightly telemetry export — standalone background script.

Orchestrates the daily telemetry export and KPI pipeline as a single
background job.  Designed to be invoked by cron, systemd, or any
process supervisor — it has **zero** FastAPI dependencies.

State machine lifecycle is managed through the ``job_runs`` table
via :mod:`src.services.job_runner`.

Usage::

    # Default (yesterday's date)
    python scripts/nightly_export.py

    # Explicit target date
    TARGET_DATE=2026-09-06 python scripts/nightly_export.py
"""

from __future__ import annotations

import csv
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ── Path bootstrap ────────────────────────────────────────────────────────
# Ensure ``src.*`` and ``packages`` are importable when running from the
# project root (mirrors the pattern used by other scripts/ entrypoints).

ROOT_DIR: Path = Path(__file__).resolve().parents[1]
API_DIR: Path = ROOT_DIR / "services" / "api"
SHARED_PY_DIR: Path = ROOT_DIR / "packages" / "shared" / "python"

for _p in (API_DIR, SHARED_PY_DIR):
    _p_str = str(_p)
    if _p_str not in sys.path:
        sys.path.insert(0, _p_str)

# Load .env if present (idempotent — safe to call multiple times)
try:
    from src.env_loader import load_env_if_available

    load_env_if_available()
except ImportError:
    pass  # env_loader is optional; env vars may already be set

from sqlmodel import Session

from src.database import get_engine
from src.services.job_runner import (
    acquire_lock,
    has_completed_for_date,
    mark_completed,
    mark_failed,
)

# ── Logging ───────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nightly_export")

# ── Constants ─────────────────────────────────────────────────────────────

JOB_NAME: str = "nightly_export"
RAW_DIR: Path = ROOT_DIR / "data" / "raw"
PIPELINE_MODULE: str = "data.pipelines.src.pipelines.telemetry_kpi_daily.run"


# ── Target date resolution ───────────────────────────────────────────────


def resolve_target_date() -> date:
    """Return the target date for this job run.

    Reads the ``TARGET_DATE`` environment variable (expected format
    ``YYYY-MM-DD``).  Falls back to yesterday (UTC) when unset or
    invalid.
    """
    raw: str | None = os.environ.get("TARGET_DATE")
    if raw:
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            logger.warning(
                "Invalid TARGET_DATE=%r — falling back to yesterday (UTC).",
                raw,
            )
    return datetime.now(timezone.utc).date() - timedelta(days=1)


# ── CSV export ────────────────────────────────────────────────────────────


def _csv_path_for(target: date) -> Path:
    """Return the canonical CSV path for *target* date."""
    return RAW_DIR / f"telemetry_{target.isoformat()}.csv"


def export_telemetry_csv(target: date) -> None:
    """Extract telemetry events for *target* date and write a CSV file.

    The query hits the ``telemetry_events`` table directly via psycopg2
    (the same approach used by the telemetry router).  If the CSV already
    exists the export is skipped silently.
    """
    csv_file: Path = _csv_path_for(target)
    if csv_file.exists():
        logger.info("CSV already exists at %s — skipping export.", csv_file)
        return

    sql_url: str | None = os.environ.get("SQL_URL")
    if not sql_url:
        raise RuntimeError(
            "SQL_URL environment variable is not set. "
            "Cannot query telemetry_events."
        )

    # Day boundaries in UTC
    day_start: datetime = datetime.combine(target, datetime.min.time(), tzinfo=timezone.utc)
    day_end: datetime = day_start + timedelta(days=1)

    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(sql_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, event_type, timestamp, payload, tags
                FROM telemetry_events
                WHERE timestamp >= %s AND timestamp < %s
                ORDER BY timestamp ASC
                """,
                (day_start, day_end),
            )
            rows: list[dict[str, Any]] = cur.fetchall()

        if not rows:
            logger.info("No telemetry events found for %s.", target.isoformat())
            # Create an empty CSV so the pipeline knows the export ran
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            csv_file.write_text("id,event_type,timestamp,payload,tags\n", encoding="utf-8")
            logger.info("Empty CSV written to %s.", csv_file)
            return

        RAW_DIR.mkdir(parents=True, exist_ok=True)

        fieldnames: list[str] = list(rows[0].keys())
        with csv_file.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                # psycopg2 RealDictCursor returns jsonb columns as Python
                # dicts — serialise them so csv.writer can handle them.
                serialised: dict[str, Any] = {}
                for key, value in row.items():
                    if isinstance(value, dict):
                        import json
                        serialised[key] = json.dumps(value, ensure_ascii=False)
                    else:
                        serialised[key] = value
                writer.writerow(serialised)

        logger.info(
            "Exported %d telemetry events to %s.", len(rows), csv_file,
        )
    finally:
        conn.close()


# ── Pipeline subprocess ───────────────────────────────────────────────────


def run_pipeline(target: date) -> None:
    """Execute the KPI pipeline as a subprocess.

    The pipeline receives the target date via the ``TARGET_DATE``
    environment variable and is invoked with ``--no-prefect``.
    """
    env: dict[str, str] = {**os.environ, "TARGET_DATE": target.isoformat()}

    logger.info(
        "Launching pipeline: python -m %s --no-prefect (TARGET_DATE=%s)",
        PIPELINE_MODULE,
        target.isoformat(),
    )

    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-m", PIPELINE_MODULE, "--no-prefect"],
        check=True,
        cwd=str(ROOT_DIR),
        env=env,
    )

    logger.info("Pipeline finished with exit code %d.", result.returncode)


# ── Main orchestration ────────────────────────────────────────────────────


def main() -> None:
    """Entry point — drives the full nightly export lifecycle."""
    target: date = resolve_target_date()
    logger.info("=== Nightly export started (target_date=%s) ===", target.isoformat())

    # ── Phase 1: Idempotency guard ────────────────────────────────────
    with Session(get_engine()) as session:
        if has_completed_for_date(session, JOB_NAME, target):
            logger.info(
                "Omission by duplicate: job=%s already completed for %s. Exiting.",
                JOB_NAME,
                target.isoformat(),
            )
            return

        # ── Phase 2: Distributed lock ─────────────────────────────────
        run = acquire_lock(session, JOB_NAME, target)
        if run is None:
            logger.info(
                "Process already running for job=%s date=%s. Exiting silently.",
                JOB_NAME,
                target.isoformat(),
            )
            return

        # ── Phase 3: Operational block ────────────────────────────────
        try:
            logger.info("Step 1/2: Exporting telemetry CSV…")
            export_telemetry_csv(target)

            logger.info("Step 2/2: Running KPI pipeline…")
            run_pipeline(target)

        except Exception:
            error_msg: str = str(sys.exc_info()[1])
            logger.exception(
                "Job %s FAILED for date=%s: %s",
                JOB_NAME,
                target.isoformat(),
                error_msg,
            )
            mark_failed(session, run.id, error_msg)
            raise  # Re-raise so the OS sees a non-zero exit code

        # ── Phase 4: Success ──────────────────────────────────────────
        mark_completed(session, run.id)
        logger.info(
            "=== Nightly export completed successfully (target_date=%s) ===",
            target.isoformat(),
        )


if __name__ == "__main__":
    main()
