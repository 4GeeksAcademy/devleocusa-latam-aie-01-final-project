"""Celery application instance for TrackFlow.

This module is intentionally isolated from database models and
SQLAlchemy/SQLModel machinery to prevent circular imports when
the Celery worker process boots.  Import only lightweight,
standalone modules here.

Usage::

    celery -A src.celery_app worker --loglevel=info
"""

from __future__ import annotations

from celery import Celery

from src.core.config import settings

# ── Application ────────────────────────────────────────────────────────
app = Celery("trackflow_worker")

# ── Broker & Result Backend ────────────────────────────────────────────
# Both point to the same Redis instance via the shared REDIS_URL variable.
app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    # Send worker events so Flower can display real-time task metrics.
    worker_send_task_events=True,
    # Accept JSON serialisation for cross-language compatibility.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # UTC timestamps for consistency across containers.
    timezone="UTC",
    enable_utc=True,
)

# ── Auto-discover tasks in sibling packages ────────────────────────────
# Adjust the list as task modules are added.
app.autodiscover_tasks([
    "src.services",
])
