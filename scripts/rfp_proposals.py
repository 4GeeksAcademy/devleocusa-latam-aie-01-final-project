#!/usr/bin/env python3
"""Consume one queued Part 1 handoff and generate/evaluate proposal sections."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
API_DIR = ROOT_DIR / "services" / "api"
PIPELINES_SRC = ROOT_DIR / "data" / "pipelines" / "src"
for candidate in (API_DIR, PIPELINES_SRC):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-iterations", type=int, default=3)
    args = parser.parse_args()
    if args.max_iterations < 1:
        parser.error("--max-iterations debe ser >= 1")
    from sqlmodel import Session
    from src.database import get_engine
    from src.models.rfp import RFPTicket
    from src.services import rfp_service

    processed_id = rfp_service.process_next_proposal_ticket(args.max_iterations)
    if processed_id is None:
        print("No hay tickets pendientes de Parte 2")
        return 0
    with Session(get_engine()) as session:
        ticket = session.get(RFPTicket, processed_id)
        print(f"ticket_id={processed_id} status={ticket.status if ticket else 'desconocido'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
