"""Reporting module for TrackFlow executive KPIs.

Provides a FastAPI router that exposes endpoints to:
  - Query pipeline execution status and metadata
  - Trigger manual pipeline runs
  - Retrieve stored KPI records from the executive dashboard

This module is intentionally decoupled from ``services/telemetry/``.
It imports pipeline orchestration directly from ``data/pipelines/``.
"""

from __future__ import annotations

from .router import router as reporting_router

__all__ = ["reporting_router"]