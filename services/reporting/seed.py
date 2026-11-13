"""Seed de KPIs ejecutivos de demostración para el panel de Reporting.

El pipeline real (Prefect + ``src/data_preparation.py``) sólo escribe registros
cuando alguien dispara ``POST /reporting/run``. En un entorno local sin
pipeline ejecutado, el dashboard muestra "N/D" en coste operativo y
satisfacción del cliente.

Este módulo rellena esos huecos con un registro de demostración validado por
``ExecutiveKPIs``, de forma **idempotente** (upsert por ``fecha_reporte`` +
``id_corrida``) y **sin sobrescribir** datos reales salvo que se pida con
``force=True``.

Uso::

    python -m reporting.seed            # inserta si no hay registros
    python -m reporting.seed --force    # reemplaza los registros de demo
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone

from reporting.models import (
    CustomerSatisfaction,
    Devoluciones,
    ExecutiveKPIs,
    OperationalCost,
    TasaEntregaTiempo,
    VolumenEnvios,
)
from reporting.store import get_all_kpi_records, save_kpi_record

DEMO_RUN_ID = "demo-seed-run"

# Los conceptos del desglose coinciden con los tramos reales de coste y se
# muestran tal cual en el panel, así que se mantienen en minúsculas sin acentos.
_COST_CONCEPTS = ("transporte", "almacenaje", "ultima_milla")


def _random_operational_cost(rng: random.Random) -> OperationalCost:
    """Genera un coste operativo plausible con desglose coherente.

    El total es siempre la suma del desglose, para que la tarjeta y el gráfico
    de conceptos no se contradigan.
    """
    breakdown = {
        "transporte": round(rng.uniform(18_000, 32_000), 2),
        "almacenaje": round(rng.uniform(8_000, 15_000), 2),
        "ultima_milla": round(rng.uniform(5_000, 12_000), 2),
    }
    total = round(sum(breakdown.values()), 2)

    return OperationalCost(total=total, currency="EUR", breakdown=breakdown)


def _positive_satisfaction(rng: random.Random) -> CustomerSatisfaction:
    """Genera una satisfacción positiva (nunca por debajo de 7.5/10)."""
    score = round(rng.uniform(7.5, 9.6), 1)

    if score >= 8.5:
        level = "alto"
    elif score >= 7.5:
        level = "medio"
    else:
        level = "bajo"

    return CustomerSatisfaction(
        score=score,
        level=level,
        penalties={
            "late_deliveries": rng.randint(0, 4),
            "returns": rng.randint(0, 3),
        },
    )


def build_demo_kpi(seed: int | None = None) -> ExecutiveKPIs:
    """Construye un registro de KPIs de demostración completo y válido."""
    rng = random.Random(seed)

    now = datetime.now(timezone.utc)
    fecha_reporte = now.date().isoformat()
    total_shipments = rng.randint(120, 480)
    on_time = rng.randint(int(total_shipments * 0.82), total_shipments)
    returns = rng.randint(0, max(1, int(total_shipments * 0.05)))

    return ExecutiveKPIs(
        fecha_reporte=fecha_reporte,
        id_corrida=DEMO_RUN_ID,
        timestamp=now.isoformat(),
        periodo=f"{now.date().isoformat()} — {(now + timedelta(days=7)).date().isoformat()}",
        volumen_envios=VolumenEnvios(
            total=total_shipments,
            por_almacen={
                "los-angeles": total_shipments // 2,
                "zaragoza": total_shipments - total_shipments // 2,
            },
        ),
        tasa_entrega_tiempo=TasaEntregaTiempo(
            porcentaje=round(on_time / total_shipments * 100, 1),
            entregas_on_time=on_time,
            entregas_totales=total_shipments,
        ),
        devoluciones=Devoluciones(
            volumen=returns,
            tasa_porcentaje=round(returns / total_shipments * 100, 2),
        ),
        operational_cost=_random_operational_cost(rng),
        customer_satisfaction=_positive_satisfaction(rng),
    )


def _records_cover_executive_kpis() -> bool:
    """Return True when the latest record already has both extra KPIs.

    Older records were persisted before ``operational_cost`` and
    ``customer_satisfaction`` existed, so their absence is not a reason to
    skip the demo seed. Only a record that already carries both is respected.
    """
    latest = get_all_kpi_records(limit=1)
    if not latest:
        return False

    return bool(
        latest[0].get("operational_cost") and latest[0].get("customer_satisfaction")
    )


def seed_demo_kpis(force: bool = False, seed: int | None = None) -> bool:
    """Inserta el KPI de demostración. Devuelve ``True`` si se escribió.

    Con ``force=False`` no hace nada cuando el último registro ya incluye coste
    operativo y satisfacción, para no pisar datos reales del pipeline.
    """
    if not force and _records_cover_executive_kpis():
        return False

    save_kpi_record(build_demo_kpi(seed=seed).model_dump(mode="json"))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed de KPIs ejecutivos de demostración.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Escribe el registro de demo aunque ya existan KPIs.",
    )
    args = parser.parse_args()

    written = seed_demo_kpis(force=args.force)
    if written:
        print("KPI de demostración insertado (coste operativo y satisfacción del cliente).")
    else:
        print("Ya existen KPIs registrados. Usa --force para reemplazarlos.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
