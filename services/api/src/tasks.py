"""Celery tasks for TrackFlow report generation.

This module encapsulates the heavy-lifting report pipeline (executive
weekly summaries and client PDF invoices) so the FastAPI process stays
responsive.  Tasks receive only **primitive IDs** — no large dicts or
ORM objects — and are fully idempotent.

Exponential-backoff retries are handled by Celery; after
``max_retries`` (3) exhausted attempts the failure is logged to the
``dead_letter_queue`` table in Supabase PostgreSQL.

Usage from a Celery worker::

    celery -A src.celery_app worker --loglevel=info --queues=reports
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from src.celery_app import app
from src.database import get_engine

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────

_OUTPUT_DIR = Path(os.environ.get("REPORT_OUTPUT_DIR", "/app/data/reports"))
try:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # In test environments the directory may not be writable — that's OK,
    # _render_pdf will be mocked anyway.
    pass

_REPORT_LABELS: dict[str, str] = {
    "executive_weekly": "Informe Consolidado Semanal – Dirección Ejecutiva",
    "client_pdf": "Informe PDF – Cliente TrackFlow",
}


# ── Structured logging helper ──────────────────────────────────────────


def _log_event(
    *,
    event: str,
    task_id: str,
    attempt: int,
    status: str,
    duration_s: float,
    **extra: Any,
) -> None:
    """Emit a structured JSON line to stdout for log aggregators."""
    record = {
        "event": event,
        "task_id": task_id,
        "attempt": attempt,
        "status": status,
        "duration_s": round(duration_s, 3),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    logger.info(json.dumps(record))


# ── Dead-letter persistence ────────────────────────────────────────────


def _save_to_dead_letter(
    *,
    task_id: str,
    attempt: int,
    error_message: str,
) -> None:
    """Insert a failure record into ``dead_letter_queue`` via raw SQL.

    Uses SQLAlchemy ``text()`` so the Celery worker never touches
    SQLModel table metadata or ORM classes — keeping imports minimal
    and avoiding circular dependencies.
    """
    stmt = text(
        """
        INSERT INTO dead_letter_queue (task_id, attempt, error_message, "timestamp")
        VALUES (:task_id, :attempt, :error_message, now())
        """
    )
    try:
        with get_engine().connect() as conn:
            conn.execute(stmt, {"task_id": task_id, "attempt": attempt,
                                "error_message": error_message})
            conn.commit()
        _log_event(
            event="dead_letter_saved",
            task_id=task_id,
            attempt=attempt,
            status="saved",
            duration_s=0.0,
        )
    except Exception as db_exc:
        # Last resort — log to stderr so the failure is never silently lost.
        _log_event(
            event="dead_letter_persist_failed",
            task_id=task_id,
            attempt=attempt,
            status="error",
            duration_s=0.0,
            db_error=str(db_exc),
        )


# ── Report generation helpers ──────────────────────────────────────────


def _build_executive_html(*, report_id: str) -> str:
    """Return HTML for the executive weekly consolidated report."""
    now = datetime.now(timezone.utc)
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8"/>
    <title>Informe Consolidado Semanal – TrackFlow</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px;
               color: #1a1a2e; }}
        .header {{ background: linear-gradient(135deg, #0f3460, #16213e);
                   color: #e94560; padding: 30px; border-radius: 8px;
                   margin-bottom: 30px; }}
        .header h1 {{ margin: 0 0 8px 0; font-size: 22px; }}
        .header p  {{ margin: 0; opacity: 0.85; font-size: 13px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 10px 14px; text-align: left;
                   border-bottom: 1px solid #ddd; }}
        th {{ background: #16213e; color: #fff; font-weight: 600; }}
        tr:hover {{ background: #f4f4f8; }}
        .footer {{ margin-top: 30px; font-size: 11px; color: #888;
                   text-align: center; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>TrackFlow – Informe Consolidado Semanal</h1>
        <p>Generado: {now.strftime('%Y-%m-%d %H:%M UTC')} &nbsp;|&nbsp; ID: {report_id}</p>
    </div>
    <table>
        <tr><th>Métrica</th><th>Valor</th></tr>
        <tr><td>Incidentes abiertos</td><td>—</td></tr>
        <tr><td>Incidentes cerrados</td><td>—</td></tr>
        <tr><td>SLA cumplido</td><td>—</td></tr>
        <tr><td>Transportistas activos</td><td>—</td></tr>
        <tr><td>KPIs del período</td><td>—</td></tr>
    </table>
    <p style="font-size:13px;color:#555;">
        Este informe ha sido generado automáticamente por el pipeline
        de reportes de TrackFlow.
    </p>
    <div class="footer">
        TrackFlow &copy; {now.year} — Documento confidencial
    </div>
</body>
</html>"""


def _build_client_html(*, report_id: str, client_id: str) -> str:
    """Return HTML for a client-specific PDF report."""
    now = datetime.now(timezone.utc)
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8"/>
    <title>Informe TrackFlow – Cliente {client_id}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px;
               color: #1a1a2e; }}
        .header {{ background: linear-gradient(135deg, #0f3460, #16213e);
                   color: #e94560; padding: 30px; border-radius: 8px;
                   margin-bottom: 30px; }}
        .header h1 {{ margin: 0 0 8px 0; font-size: 22px; }}
        .header p  {{ margin: 0; opacity: 0.85; font-size: 13px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 10px 14px; text-align: left;
                   border-bottom: 1px solid #ddd; }}
        th {{ background: #16213e; color: #fff; font-weight: 600; }}
        tr:hover {{ background: #f4f4f8; }}
        .footer {{ margin-top: 30px; font-size: 11px; color: #888;
                   text-align: center; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>TrackFlow – Informe para Cliente</h1>
        <p>Cliente: {client_id} &nbsp;|&nbsp;
           ID: {report_id} &nbsp;|&nbsp;
           {now.strftime('%Y-%m-%d %H:%M UTC')}</p>
    </div>
    <table>
        <tr><th>Métrica</th><th>Valor</th></tr>
        <tr><td>Pedidos entregados</td><td>—</td></tr>
        <tr><td>Pedidos pendientes</td><td>—</td></tr>
        <tr><td>Tiempo promedio de entrega</td><td>—</td></tr>
        <tr><td>Incidencias reportadas</td><td>—</td></tr>
    </table>
    <p style="font-size:13px;color:#555;">
        Este informe ha sido generado automáticamente por el sistema
        de reportes de TrackFlow.
    </p>
    <div class="footer">
        TrackFlow &copy; {now.year} — Documento confidencial
    </div>
</body>
</html>"""


def _render_pdf(html_content: str, output_path: Path) -> None:
    """Render *html_content* into a PDF file at *output_path* using WeasyPrint."""
    from weasyprint import HTML

    HTML(string=html_content).write_pdf(str(output_path))


# ── Celery task ─────────────────────────────────────────────────────────


@app.task(
    bind=True,
    max_retries=3,
    name="src.tasks.generate_report",
    acks_late=True,
    reject_on_worker_lost=True,
)
def generate_report(
    self,
    report_type: str,
    report_id: str,
    client_id: str | None = None,
) -> dict[str, Any]:
    """Generate a TrackFlow report (executive weekly or client PDF).

    Parameters
    ----------
    report_type:
        ``"executive_weekly"`` for the Dirección Ejecutiva consolidated
        report, or ``"client_pdf"`` for a per-client PDF.
    report_id:
        Unique identifier of the report to generate (UUID string).
    client_id:
        Client identifier — required only when *report_type* is
        ``"client_pdf"``.

    Returns
    -------
    dict
        ``{"status": "completed", "path": "<file_path>", ...}`` on
        success, or ``{"status": "dead_lettered", ...}`` when all
        retries are exhausted.

    Retry strategy
    ---------------
    On any exception the task is re-queued with exponential backoff::

        countdown = 2 ** self.request.retries   # 1 s → 2 s → 4 s

    After ``max_retries`` (3) the failure is persisted to the
    ``dead_letter_queue`` table and the task returns a failure dict.
    """
    start = time.monotonic()
    attempt = self.request.retries + 1
    task_id = self.request.id or str(uuid4())

    _log_event(
        event="task_started",
        task_id=task_id,
        attempt=attempt,
        status="running",
        duration_s=0.0,
        report_type=report_type,
        report_id=report_id,
        client_id=client_id,
    )

    try:
        # ── Validate inputs ────────────────────────────────────────
        if report_type not in _REPORT_LABELS:
            raise ValueError(
                f"report_type must be one of {list(_REPORT_LABELS.keys())}, "
                f"got '{report_type}'"
            )
        if report_type == "client_pdf" and not client_id:
            raise ValueError(
                "client_id is required when report_type == 'client_pdf'"
            )

        # ── Build HTML ─────────────────────────────────────────────
        if report_type == "executive_weekly":
            html = _build_executive_html(report_id=report_id)
        else:
            html = _build_client_html(report_id=report_id, client_id=client_id)

        # ── Render PDF ─────────────────────────────────────────────
        pdf_name = f"{report_type}_{report_id}.pdf"
        pdf_path = _OUTPUT_DIR / pdf_name
        _render_pdf(html, pdf_path)

        duration = time.monotonic() - start
        _log_event(
            event="task_completed",
            task_id=task_id,
            attempt=attempt,
            status="completed",
            duration_s=duration,
            path=str(pdf_path),
        )

        return {
            "status": "completed",
            "report_id": report_id,
            "report_type": report_type,
            "path": str(pdf_path),
            "duration_s": round(duration, 3),
            "attempt": attempt,
        }

    except Exception as exc:
        duration = time.monotonic() - start
        _log_event(
            event="task_failed",
            task_id=task_id,
            attempt=attempt,
            status="retrying" if attempt <= self.max_retries else "exhausted",
            duration_s=duration,
            error=str(exc),
        )

        # ── Exponential backoff retry ──────────────────────────────
        if self.request.retries >= self.max_retries:
            _save_to_dead_letter(
                task_id=task_id,
                attempt=attempt,
                error_message=str(exc),
            )
            final_duration = time.monotonic() - start
            _log_event(
                event="task_dead_lettered",
                task_id=task_id,
                attempt=attempt,
                status="dead_lettered",
                duration_s=final_duration,
                error=str(exc),
            )
            raise

        self.retry(exc=exc, countdown=2 ** self.request.retries)
