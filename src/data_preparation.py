"""Preparacion temporal del historico de ventas de TrackFlow."""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd
from pandas.api.types import is_numeric_dtype
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler


DATE_COLUMN: Final = "month"
TARGET_COLUMN: Final = "revenue_eur"
NUMERIC_FEATURES: Final[tuple[str, ...]] = (
    "shipments_processed",
    "avg_revenue_per_shipment_eur",
)
EXPECTED_COLUMNS: Final[frozenset[str]] = frozenset(
    {DATE_COLUMN, TARGET_COLUMN, "market", *NUMERIC_FEATURES}
)
DEFAULT_DATA_PATHS: Final[tuple[Path, ...]] = (
    Path("data/raw/trackflow_sales.csv"),
    Path("content/contexts/sales-forecasting/trackflow/trackflow_sales.csv"),
)
TRAIN_YEARS: Final = 8
TEST_YEARS: Final = 2


@dataclass(frozen=True)
class PreparedSalesData:
    """Conjuntos cronologicos preparados y transformadores ajustados."""

    X_train: pd.DataFrame
    X_test: pd.DataFrame
    y_train: pd.Series
    y_test: pd.Series
    scaler: StandardScaler
    imputer: SimpleImputer


def resolve_data_path(csv_path: Path | str | None = None) -> Path:
    """Localiza el historico en la ruta indicada o en las rutas del proyecto."""
    if csv_path is not None:
        resolved_path = Path(csv_path)
        if not resolved_path.is_file():
            raise FileNotFoundError(f"No se encontro el dataset: {resolved_path}")
        return resolved_path

    for candidate in DEFAULT_DATA_PATHS:
        if candidate.is_file():
            return candidate

    searched_paths = ", ".join(str(path) for path in DEFAULT_DATA_PATHS)
    raise FileNotFoundError(f"No se encontro el dataset en: {searched_paths}")


def load_sales_data(csv_path: Path | str | None = None) -> pd.DataFrame:
    """Carga, valida y ordena el historico mensual de ventas."""
    data = pd.read_csv(resolve_data_path(csv_path), na_values=["", " "])
    missing_columns = EXPECTED_COLUMNS.difference(data.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Faltan columnas requeridas del contexto TrackFlow: {missing}")

    data = data.loc[:, list(EXPECTED_COLUMNS)].copy()
    text_columns = data.select_dtypes(include=["object", "string"]).columns
    data[text_columns] = data[text_columns].replace(r"^\s*$", pd.NA, regex=True)
    data[DATE_COLUMN] = pd.to_datetime(data[DATE_COLUMN], errors="coerce")

    for column in (TARGET_COLUMN, *NUMERIC_FEATURES):
        data[column] = pd.to_numeric(data[column], errors="coerce")

    # Sin fecha no se puede respetar la secuencia y sin objetivo no se puede
    # entrenar; por eso esas filas se eliminan en lugar de inventar etiquetas.
    data = data.dropna(subset=[DATE_COLUMN, TARGET_COLUMN])
    if data.empty:
        raise ValueError("No quedan registros validos despues de limpiar fecha y objetivo")

    # El mercado aporta contexto descriptivo, pero no se escala ni se usa para
    # predecir; una categoria explicita conserva esas filas sin fabricar datos.
    data["market"] = data["market"].fillna("unknown")

    if not all(is_numeric_dtype(data[column]) for column in NUMERIC_FEATURES):
        raise TypeError("Las variables predictoras deben ser numericas")

    return data.sort_values(DATE_COLUMN, kind="stable").reset_index(drop=True)


def _split_by_year(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    years = sorted(int(year) for year in data[DATE_COLUMN].dt.year.unique())
    expected_year_count = TRAIN_YEARS + TEST_YEARS
    if len(years) != expected_year_count:
        raise ValueError(
            f"Se esperaban {expected_year_count} anos y se encontraron {len(years)}"
        )
    if years != list(range(years[0], years[0] + expected_year_count)):
        raise ValueError("El historico debe contener diez anos calendario consecutivos")

    train_years = set(years[:TRAIN_YEARS])
    test_years = set(years[-TEST_YEARS:])
    train_data = data[data[DATE_COLUMN].dt.year.isin(train_years)].copy()
    test_data = data[data[DATE_COLUMN].dt.year.isin(test_years)].copy()

    if train_data.empty or test_data.empty:
        raise ValueError("La division temporal genero un conjunto vacio")
    if train_data[DATE_COLUMN].max() >= test_data[DATE_COLUMN].min():
        raise ValueError("La division temporal contiene solapamiento")
    return train_data, test_data


def prepare_sales_data(csv_path: Path | str | None = None) -> PreparedSalesData:
    """Limpia, divide por tiempo e imputa y escala las variables predictoras."""
    data = load_sales_data(csv_path)
    train_data, test_data = _split_by_year(data)

    X_train_raw = train_data.loc[:, NUMERIC_FEATURES]
    X_test_raw = test_data.loc[:, NUMERIC_FEATURES]

    # La mediana es robusta ante picos estacionales de volumen. Tanto el
    # imputador como el escalador aprenden solo del pasado para evitar leakage.
    imputer = SimpleImputer(strategy="median")
    X_train_imputed = imputer.fit_transform(X_train_raw)
    X_test_imputed = imputer.transform(X_test_raw)

    scaler = StandardScaler()
    X_train = pd.DataFrame(
        scaler.fit_transform(X_train_imputed),
        columns=NUMERIC_FEATURES,
        index=train_data.index,
    )
    X_test = pd.DataFrame(
        scaler.transform(X_test_imputed),
        columns=NUMERIC_FEATURES,
        index=test_data.index,
    )

    return PreparedSalesData(
        X_train=X_train,
        X_test=X_test,
        y_train=train_data[TARGET_COLUMN].copy(),
        y_test=test_data[TARGET_COLUMN].copy(),
        scaler=scaler,
        imputer=imputer,
    )


if __name__ == "__main__":
    prepared = prepare_sales_data()
    print(f"Entrenamiento: {len(prepared.X_train)} registros")
    print(f"Prueba: {len(prepared.X_test)} registros")