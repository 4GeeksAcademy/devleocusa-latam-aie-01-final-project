"""Pruebas de la frontera temporal del pipeline de ventas."""

from pathlib import Path
import sys

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from data_preparation import DATE_COLUMN, _split_by_year


@pytest.fixture
def consecutive_sales_data() -> pd.DataFrame:
    """Crea diez anos completos de registros mensuales unicos."""
    months = pd.date_range("2016-01-01", periods=120, freq="MS")
    return pd.DataFrame(
        {
            DATE_COLUMN: months,
            "record_id": [f"sale-{index:03d}" for index in range(120)],
            "revenue_eur": [500_000.0 + index * 1_000.0 for index in range(120)],
            "shipments_processed": [40_000 + index for index in range(120)],
            "avg_revenue_per_shipment_eur": [12.5 + index / 100 for index in range(120)],
            "market": "consolidated",
        }
    )


def test_chronological_split(consecutive_sales_data: pd.DataFrame) -> None:
    """La ultima fecha de entrenamiento precede a toda fecha de prueba."""
    train_data, test_data = _split_by_year(consecutive_sales_data)

    assert train_data[DATE_COLUMN].max() < test_data[DATE_COLUMN].min()


def test_split_proportions(consecutive_sales_data: pd.DataFrame) -> None:
    """Ocho anos mensuales van a entrenamiento y dos anos a prueba."""
    train_data, test_data = _split_by_year(consecutive_sales_data)

    assert len(train_data) == 8 * 12
    assert len(test_data) == 2 * 12
    assert train_data[DATE_COLUMN].dt.year.nunique() == 8
    assert test_data[DATE_COLUMN].dt.year.nunique() == 2


def test_no_data_leakage(consecutive_sales_data: pd.DataFrame) -> None:
    """Ningun indice, identificador ni fila futura aparece en entrenamiento."""
    train_data, test_data = _split_by_year(consecutive_sales_data)

    assert train_data.index.intersection(test_data.index).empty
    assert set(train_data["record_id"]).isdisjoint(test_data["record_id"])

    shared_rows = train_data.merge(test_data, how="inner", on=list(consecutive_sales_data.columns))
    assert shared_rows.empty