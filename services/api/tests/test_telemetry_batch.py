#!/usr/bin/env python3
"""
QA Test Script — POST /telemetry/events
========================================
Envía un lote mixto de 4 eventos de telemetría (3 válidos + 1 inválido)
al endpoint FastAPI y muestra la respuesta.

Uso:
    python3 test_telemetry_batch.py          # usa defaults
    python3 test_telemetry_batch.py --url http://localhost:8000

Requiere: pip install requests
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

# ──────────────────────────────────────────────
# Construcción del lote (batch)
# ──────────────────────────────────────────────

def build_batch() -> list[dict[str, Any]]:
    """Retorna una lista de 4 eventos (3 válidos + 1 inválido)."""

    # ── Evento 1: Válido — Orden de entrada de inventario ──────────
    entrada: dict[str, Any] = {
        "eventId": "a1b2c3d4-0001-4000-8000-000000000001",
        "timestamp": "2026-08-27T10:15:00Z",
        "sessionId": "session-entrada-001",
        "userId": "usr-bodega-01",
        "event_type": "inventory.entry",
        "schemaVersion": "1.0",
        "requestId": "req-ent-001",
        "properties": {
            "sku": "LAP-ACER-15",
            "producto": "Laptop Acer Aspire 15",
            "cantidad": 50,
            "ubicacion": "Warehouse-A",
            "proveedor": "Acer Corp",
        },
    }

    # ── Evento 2: Válido — Orden de salida de inventario ───────────
    salida: dict[str, Any] = {
        "eventId": "b2c3d4e5-0002-4000-8000-000000000002",
        "timestamp": "2026-08-27T10:30:00Z",
        "sessionId": "session-salida-002",
        "userId": "usr-bodega-01",
        "event_type": "inventory.exit",
        "schemaVersion": "1.0",
        "requestId": "req-sal-002",
        "properties": {
            "sku": "LAP-ACER-15",
            "producto": "Laptop Acer Aspire 15",
            "cantidad": 5,
            "destino": "Cliente #4521",
            "orden_compra": "OC-2026-08823",
        },
    }

    # ── Evento 3: Válido — Login fallido (técnico) ─────────────────
    login_fallido: dict[str, Any] = {
        "eventId": "c3d4e5f6-0003-4000-8000-000000000003",
        "timestamp": "2026-08-27T09:45:00Z",
        "sessionId": "session-auth-003",
        "userId": None,
        "event_type": "auth.login_failed",
        "schemaVersion": "1.0",
        "requestId": "req-auth-003",
        "properties": {
            "ip_address": "192.168.1.100",
            "attempted_username": "admin_antiguo",
            "reason": "invalid_password",
            "attempt_count": 3,
        },
    }

    # ── Evento 4: INVÁLIDO — Falta event_type (campo obligatorio) ──
    invalido: dict[str, Any] = {
        "eventId": "d4e5f6a7-0004-4000-8000-000000000004",
        "timestamp": "2026-08-27T11:00:00Z",
        # "event_type" está AUSENTE — esto forzará ValidationError
        "sessionId": "session-bad-004",
        "userId": "usr-test",
        "schemaVersion": "1.0",
        "requestId": "req-bad-004",
        "properties": {
            "debug_info": "Esto no debería guardarse",
        },
    }

    return [entrada, salida, login_fallido, invalido]


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="QA: enviar lote mixto de telemetría al endpoint FastAPI"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="URL base del servidor FastAPI (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--endpoint",
        default="/telemetry/events",
        help="Ruta del endpoint (default: /telemetry/events)",
    )
    args = parser.parse_args()

    full_url = args.url.rstrip("/") + "/" + args.endpoint.lstrip("/")
    batch = build_batch()

    payload: dict[str, Any] = {"events": batch}

    print("=" * 60)
    print("🧪 QA TEST — POST /telemetry/events")
    print("=" * 60)
    print(f"\n📍 URL:     {full_url}")
    print(f"📦 Eventos: {len(batch)} totales")
    print(f"   ├─ Válidos:   3  (entrada, salida, login fallido)")
    print(f"   └─ Inválidos: 1  (falta event_type)\n")

    print("─" * 60)
    print("📤 Payload enviado:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("─" * 60)

    try:
        response = requests.post(full_url, json=payload, timeout=10)
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: No se pudo conectar al servidor.")
        print(f"   Asegúrate de que FastAPI esté corriendo en {args.url}")
        print("   Comando sugerido:")
        print(f'   cd services/api && uvicorn src.fastapi_server:app --reload --port 8000\n')
        sys.exit(1)

    print(f"\n📥 Respuesta HTTP {response.status_code}")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))

    # ── Validación automática del resultado ──────────────────────────────
    print("\n" + "=" * 60)
    print("🔍 VERIFICACIÓN AUTOMÁTICA")
    print("=" * 60)

    if response.status_code != 200:
        print(f"❌ Status code: {response.status_code} (esperado: 200)")
    else:
        print("✅ Status code: 200")

    data = response.json()
    received = data.get("received", 0)
    stored = data.get("stored", 0)
    rejected = data.get("rejected", 0)

    checks = [
        ("received == 4", received == 4),
        ("stored == 3", stored == 3),
        ("rejected == 1", rejected == 1),
        ("stored + rejected == received", stored + rejected == received),
    ]

    for desc, ok in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {desc}  (got: received={received}, stored={stored}, rejected={rejected})")

    print()


if __name__ == "__main__":
    main()