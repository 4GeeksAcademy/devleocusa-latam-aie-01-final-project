"""Job runner state machine for automated nightly scripts.

This module manages the lifecycle and idempotency of background jobs
via the ``job_runs`` table in Supabase (PostgreSQL).

**Design invariants:**
- ZERO FastAPI dependencies — consumed by CLI scripts only.
- Distributed lock = existence of a ``'processing'`` row for the same
  ``(job_name, target_date)`` pair.  No external cache or flags.
- All timestamps are UTC (``datetime.now(timezone.utc)``).
- Every public function receives an open SQLModel ``Session`` so the
  caller controls the transaction boundary.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from src.models.sql_models import JobRunTable

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────

class JobStatus:
    """Literal status values for ``job_runs.status``."""

    PENDING: str = "pending"
    PROCESSING: str = "processing"
    COMPLETED: str = "completed"
    FAILED: str = "failed"


# ── Public API ────────────────────────────────────────────────────────────


def has_completed_for_date(
    session: Session,
    job_name: str,
    target_date: date,
) -> bool:
    """Return ``True`` if a **completed** run already exists for *job_name* on *target_date*.

    This is the idempotency guard: callers should skip execution when this
    returns ``True``.

    Parameters
    ----------
    session:
        An active SQLModel/SQLAlchemy session.
    job_name:
        Logical name of the job (e.g. ``'nightly_export'``).
    target_date:
        Calendar date the job targets.
    """
    stmt = (
        select(JobRunTable)
        .where(
            JobRunTable.job_name == job_name,
            JobRunTable.target_date == target_date.isoformat(),
            JobRunTable.status == JobStatus.COMPLETED,
        )
        .limit(1)
    )
    result = session.exec(stmt).first()
    return result is not None


def acquire_lock(
    session: Session,
    job_name: str,
    target_date: date,
) -> Optional[JobRunTable]:
    """Try to acquire the distributed lock by inserting a ``'processing'`` row.

    **Lock semantics:** If a row with ``status = 'processing'`` already
    exists for the same ``(job_name, target_date)``, the lock is held by
    another process — return ``None`` and abort silently.

    On success the newly created ``JobRunTable`` row is returned (with
    ``started_at`` set to the current UTC time).  The caller **must**
    later call :func:`mark_completed` or :func:`mark_failed` to release
    the lock.

    Parameters
    ----------
    session:
        An active SQLModel/SQLAlchemy session.
    job_name:
        Logical name of the job.
    target_date:
        Calendar date the job targets.

    Returns
    -------
    The created ``JobRunTable`` row, or ``None`` if the lock is already held.
    """
    existing = _find_processing(session, job_name, target_date)
    if existing is not None:
        logger.info(
            "Lock already held for job=%s date=%s (run_id=%s). Skipping.",
            job_name,
            target_date.isoformat(),
            existing.id,
        )
        return None

    now_utc = datetime.now(timezone.utc)
    run = JobRunTable(
        job_name=job_name,
        target_date=target_date.isoformat(),
        status=JobStatus.PROCESSING,
        started_at=now_utc,
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    logger.info(
        "Lock acquired for job=%s date=%s (run_id=%s).",
        job_name,
        target_date.isoformat(),
        run.id,
    )
    return run


def mark_completed(session: Session, job_id: str) -> JobRunTable:
    """Transition a run to ``'completed'`` and stamp ``finished_at``.

    Parameters
    ----------
    session:
        An active SQLModel/SQLAlchemy session.
    job_id:
        UUID of the ``job_runs`` row (the ``id`` column).

    Raises
    ------
    ValueError
        If no row with the given *job_id* exists.
    """
    run = _get_by_id(session, job_id)
    run.status = JobStatus.COMPLETED
    run.finished_at = datetime.now(timezone.utc)
    session.add(run)
    session.commit()
    session.refresh(run)

    logger.info("Job run %s marked COMPLETED.", job_id)
    return run


def mark_failed(
    session: Session,
    job_id: str,
    error_message: str,
) -> JobRunTable:
    """Transition a run to ``'failed'``, stamp ``finished_at``, and persist the error.

    Parameters
    ----------
    session:
        An active SQLModel/SQLAlchemy session.
    job_id:
        UUID of the ``job_runs`` row.
    error_message:
        Free-text error description (traceback, exception string, etc.).

    Raises
    ------
    ValueError
        If no row with the given *job_id* exists.
    """
    run = _get_by_id(session, job_id)
    run.status = JobStatus.FAILED
    run.finished_at = datetime.now(timezone.utc)
    run.error_message = error_message
    session.add(run)
    session.commit()
    session.refresh(run)

    logger.warning("Job run %s marked FAILED: %s", job_id, error_message)
    return run


# ── Internal helpers ──────────────────────────────────────────────────────


def _find_processing(
    session: Session,
    job_name: str,
    target_date: date,
) -> Optional[JobRunTable]:
    """Return the existing ``'processing'`` row for *(job_name, target_date)*, or ``None``."""
    stmt = (
        select(JobRunTable)
        .where(
            JobRunTable.job_name == job_name,
            JobRunTable.target_date == target_date.isoformat(),
            JobRunTable.status == JobStatus.PROCESSING,
        )
        .limit(1)
    )
    return session.exec(stmt).first()


def _get_by_id(session: Session, job_id: str) -> JobRunTable:
    """Fetch a ``JobRunTable`` by its UUID or raise ``ValueError``."""
    run = session.get(JobRunTable, job_id)
    if run is None:
        raise ValueError(f"No job_run found with id={job_id!r}")
    return run
