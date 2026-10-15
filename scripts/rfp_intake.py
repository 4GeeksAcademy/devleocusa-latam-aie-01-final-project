#!/usr/bin/env python3
"""CLI del pipeline rfp_intake — reproceso manual y smoke runs SIN segundo API.

Reutiliza la misma capa de servicio que el endpoint HTTP (rfp_service), así
que la verdad del ticket en Supabase es única.

Uso::

    # Subida directa + pipeline sincrónico (smoke run)
    python scripts/rfp_intake.py run --pdf rfp-requests/modaviva/CONTEXT-trackflow-request-1.pdf

    # Reprocesar un ticket existente (idempotente: limpia artefactos previos)
    python scripts/rfp_intake.py reprocess --ticket-id <uuid>

    # Inspeccionar un ticket tras el run
    python scripts/rfp_intake.py show --ticket-id <uuid>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
API_DIR = ROOT_DIR / "services" / "api"
PIPELINES_SRC = ROOT_DIR / "data" / "pipelines" / "src"

for path in (str(API_DIR), str(PIPELINES_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _require_reachable_supabase() -> None:
    from src.database import get_engine  # noqa: F401  (validates SQL_URL presence)

    get_engine()  # raises RuntimeError if SQL_URL is missing


def cmd_run(args: argparse.Namespace) -> int:
    from sqlmodel import Session

    from src.database import get_engine
    from src.services import rfp_service

    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"[error] No existe el PDF: {pdf_path}", file=sys.stderr)
        return 2

    _require_reachable_supabase()
    pdf_bytes = pdf_path.read_bytes()
    ticket = rfp_service.create_ticket_and_store_pdf(pdf_path.name, pdf_bytes)
    print(f"[info] ticket {ticket.id} creado (analizando) — procesando en sincrono...")

    # Same code path as the HTTP background task, run inline for visibility.
    rfp_service.process_ticket(ticket.id)

    with Session(get_engine()) as session:
        bundle = rfp_service.get_ticket_bundle(session, ticket.id)
        if bundle is None:
            print("[error] ticket desaparecio tras procesar", file=sys.stderr)
            return 1
        stored, document, sections = bundle
        print(f"[result] estado: {stored.status}")
        if stored.error_detail:
            print(f"[result] detalle: {stored.error_detail}")
        if document is not None:
            print(
                f"[result] org={document.issuing_organization!r} "
                f"lang={document.detected_language} words={document.word_count} "
                f"tokens~{document.estimated_token_cost}"
            )
        for section in sections:
            print(f"  - {section.department} [{section.status}] → pedir a {section.contact_name}")
    return 0


def cmd_reprocess(args: argparse.Namespace) -> int:
    from src.services import rfp_service

    _require_reachable_supabase()
    print(f"[info] reprocesando ticket {args.ticket_id}...")
    rfp_service.process_ticket(args.ticket_id)
    print("[done] reproceso finalizado")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    from sqlmodel import Session

    from src.database import get_engine
    from src.services import rfp_service

    _require_reachable_supabase()
    with Session(get_engine()) as session:
        bundle = rfp_service.get_ticket_bundle(session, args.ticket_id)
        if bundle is None:
            print(f"[error] ticket no encontrado: {args.ticket_id}", file=sys.stderr)
            return 1
        ticket, document, sections = bundle
        payload = {
            "ticket": {
                "id": ticket.id,
                "status": ticket.status,
                "original_filename": ticket.original_filename,
                "is_rfp": ticket.is_rfp,
                "classification_reason": ticket.classification_reason,
                "synthesis_summary": ticket.synthesis_summary,
                "error_detail": ticket.error_detail,
            },
            "document": document.dict() if document else None,
            "sections": [
                {
                    "department": s.department,
                    "contact_name": s.contact_name,
                    "status": s.status,
                    "key_aspects": json.loads(s.key_aspects) if s.key_aspects else None,
                }
                for s in sections
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CLI del pipeline rfp_intake (TrackFlow)")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Recibir un PDF y procesarlo de punta a punta")
    run_parser.add_argument("--pdf", required=True, help="Ruta al archivo PDF")
    run_parser.set_defaults(func=cmd_run)

    reprocess_parser = sub.add_parser("reprocess", help="Reejecutar el pipeline de un ticket")
    reprocess_parser.add_argument("--ticket-id", required=True)
    reprocess_parser.set_defaults(func=cmd_reprocess)

    show_parser = sub.add_parser("show", help="Ver el estado persistido de un ticket")
    show_parser.add_argument("--ticket-id", required=True)
    show_parser.set_defaults(func=cmd_show)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
