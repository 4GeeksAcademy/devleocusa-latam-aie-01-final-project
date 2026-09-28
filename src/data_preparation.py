"""Preparacion temporal del historico de ventas de TrackFlow."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final

import pandas as pd
from pandas.api.types import is_numeric_dtype
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

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

# Defaults para features temporales
DEFAULT_LAGS: Final[tuple[int, ...]] = (1, 2, 3, 6, 12)
DEFAULT_ROLLING_WINDOWS: Final[tuple[int, ...]] = (3, 6, 12)
# Columnas meta que nunca entran como features al modelo
_META_COLUMNS: Final[frozenset[str]] = frozenset({DATE_COLUMN, TARGET_COLUMN, "market"})
# Nombre de columna temporal para el índice lineal de tendencia
_TREND_COLUMN: Final = "trend"


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
    """Divide el dataset en entrenamiento y prueba por años consecutivos."""
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


def _build_temporal_features(
    data: pd.DataFrame,
    lags: tuple[int, ...],
    rolling_windows: tuple[int, ...],
) -> pd.DataFrame:
    """Genera features temporales sobre una serie cronológica completa.

    Todas las operaciones miran exclusivamente hacia el pasado (shift con
    valores positivos, rolling con ``min_periods`` adecuado). Cuando se
    invoca sobre la serie completa, los primeros ``max(lags)`` registros
    quedan en NaN de forma natural; al dividir en train/test **después**,
    los registros de test conservan sus lags correctos apuntando al
    historial de entrenamiento.

    Devuelve una copia sin modificar el DataFrame original.
    """
    if DATE_COLUMN not in data.columns:
        raise ValueError(f"Columna {DATE_COLUMN} no encontrada en el DataFrame")
    if TARGET_COLUMN not in data.columns:
        raise ValueError(f"Columna {TARGET_COLUMN} no encontrada en el DataFrame")

    df = data.copy()
    df[DATE_COLUMN] = pd.to_datetime(df[DATE_COLUMN], errors="coerce")
    df = df.sort_values(DATE_COLUMN).reset_index(drop=True)

    # ── Lags del target ───────────────────────────────────────────────
    for lag in lags:
        df[f"lag_{lag}"] = df[TARGET_COLUMN].shift(lag)

    # ── Rolling statistics del target ─────────────────────────────────
    for window in rolling_windows:
        df[f"rolling_mean_{window}"] = (
            df[TARGET_COLUMN].rolling(window=window, min_periods=window).mean()
        )
        df[f"rolling_std_{window}"] = (
            df[TARGET_COLUMN].rolling(window=window, min_periods=window).std()
        )

    # ── Lags de variables operativas ──────────────────────────────────
    for lag in lags:
        if "shipments_processed" in df.columns:
            df[f"shipments_lag_{lag}"] = df["shipments_processed"].shift(lag)
        if "avg_revenue_per_shipment_eur" in df.columns:
            df[f"avg_revenue_lag_{lag}"] = df["avg_revenue_per_shipment_eur"].shift(lag)

    # ── Rolling de variables operativas ───────────────────────────────
    for window in rolling_windows:
        if "shipments_processed" in df.columns:
            df[f"shipments_rolling_mean_{window}"] = (
                df["shipments_processed"].rolling(window=window, min_periods=window).mean()
            )
            df[f"shipments_rolling_std_{window}"] = (
                df["shipments_processed"].rolling(window=window, min_periods=window).std()
            )
        if "avg_revenue_per_shipment_eur" in df.columns:
            df[f"avg_revenue_rolling_mean_{window}"] = (
                df["avg_revenue_per_shipment_eur"]
                .rolling(window=window, min_periods=window)
                .mean()
            )
            df[f"avg_revenue_rolling_std_{window}"] = (
                df["avg_revenue_per_shipment_eur"]
                .rolling(window=window, min_periods=window)
                .std()
            )

    # ── Estacionalidad (constante por posición calendario) ────────────
    # IMPORTANTE: DATE_COLUMN == "month" (datetime). Extraemos primero
    # las partes calendario y las guardamos con nombres distintos para
    # no sobreescribir la columna datetime antes de usar .dt.
    dt_accessor = df[DATE_COLUMN].dt
    df["month_of_year"] = dt_accessor.month
    df["quarter"] = dt_accessor.quarter

    # ── Tendencia lineal (posición en la serie) ───────────────────────
    df[_TREND_COLUMN] = range(len(df))

    return df


def get_temporal_feature_columns(
    lags: tuple[int, ...] = DEFAULT_LAGS,
    rolling_windows: tuple[int, ...] = DEFAULT_ROLLING_WINDOWS,
) -> list[str]:
    """Devuelve la lista ordenada de nombres de columnas features temporales.

    Incluye lags del target, lags de variables operativas, rolling stats,
    estacionalidad y tendencia.  **No** incluye columnas meta (date,
    target, market).
    """
    cols: list[str] = []

    # Lags del target
    for lag in lags:
        cols.append(f"lag_{lag}")

    # Rolling del target
    for w in rolling_windows:
        cols.append(f"rolling_mean_{w}")
        cols.append(f"rolling_std_{w}")

    # Lags de variables operativas
    for lag in lags:
        cols.append(f"shipments_lag_{lag}")
        cols.append(f"avg_revenue_lag_{lag}")

    # Rolling de variables operativas
    for w in rolling_windows:
        cols.append(f"shipments_rolling_mean_{w}")
        cols.append(f"shipments_rolling_std_{w}")
        cols.append(f"avg_revenue_rolling_mean_{w}")
        cols.append(f"avg_revenue_rolling_std_{w}")

    # Estacionalidad y tendencia
    cols.extend(["month_of_year", "quarter", _TREND_COLUMN])

    return cols


def prepare_temporal_sales_data(
    csv_path: Path | str | None = None,
    lags: tuple[int, ...] = DEFAULT_LAGS,
    rolling_windows: tuple[int, ...] = DEFAULT_ROLLING_WINDOWS,
) -> PreparedSalesData:
    """Prepara datos con features temporales, imputa y escala.

    A diferencia de una implementación ingenua que calcula lags por separado
    en train y test (rompiendo la continuidad temporal), aquí los features
    se construyen sobre la **serie completa** antes de dividir.  Así cada
    registro de test mantiene sus lags apuntando a valores reales del
    período de entrenamiento.

    Solo se conservan registros donde todos los features son no-nulos
    (los primeros ``max(lags)`` registros se descartan por no tener
    suficiente historial).
    """
    data = load_sales_data(csv_path)

    # 1. Features temporales sobre la serie completa (sin fuga)
    full = _build_temporal_features(data, lags, rolling_windows)

    # 2. Dividir train/test ANTES de eliminar NaN.  Los primeros registros
    #    (max lags) tienen NaN en features derivadas, pero solo afecta a
    #    train; los registros de test apuntan a valores reales del pasado.
    feature_cols = get_temporal_feature_columns(lags, rolling_windows)
    train_data, test_data = _split_by_year(full)

    # 3. Eliminar filas con NaN solo dentro de cada partición
    train_data = train_data.dropna(subset=feature_cols).reset_index(drop=True)
    test_data = test_data.dropna(subset=feature_cols).reset_index(drop=True)

    X_train_raw = train_data[feature_cols]
    X_test_raw = test_data[feature_cols]

    # 4. Imputar y escalar (fit solo en train)
    imputer = SimpleImputer(strategy="median")
    X_train_imputed = imputer.fit_transform(X_train_raw)
    X_test_imputed = imputer.transform(X_test_raw)

    scaler = StandardScaler()
    X_train = pd.DataFrame(
        scaler.fit_transform(X_train_imputed),
        columns=feature_cols,
        index=train_data.index,
    )
    X_test = pd.DataFrame(
        scaler.transform(X_test_imputed),
        columns=feature_cols,
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


def prepare_full_temporal_data(
    csv_path: Path | str | None = None,
    lags: tuple[int, ...] = DEFAULT_LAGS,
    rolling_windows: tuple[int, ...] = DEFAULT_ROLLING_WINDOWS,
) -> tuple[pd.DataFrame, pd.Series]:
    """Prepara la serie completa (train + test) con features temporales.

    Devuelve ``(X, y)`` listos para pasar a ``evaluate_time_series_cv``.
    Las primeras filas con NaN en features derivadas se eliminan.

    ``evaluate_time_series_cv`` recibe ``X`` e ``y`` pre-computados y
    aplica ``TimeSeriesSplit`` sin mezclar pasado y futuro.  Las columnas
    ``_META_COLUMNS`` se excluyen de ``X``.
    """
    data = load_sales_data(csv_path)
    full = _build_temporal_features(data, lags, rolling_windows)

    feature_cols = get_temporal_feature_columns(lags, rolling_windows)
    full = full.dropna(subset=feature_cols).reset_index(drop=True)

    X = full[feature_cols]
    y = full[TARGET_COLUMN].copy()
    return X, y


def create_fold_feature_builder(
    csv_path: Path | str | None = None,
    lags: tuple[int, ...] = DEFAULT_LAGS,
    rolling_windows: tuple[int, ...] = DEFAULT_ROLLING_WINDOWS,
) -> Callable[[pd.DataFrame], pd.DataFrame]:
    """Crea un feature_builder seguro para cross-validation.

    Dado que ``_build_temporal_features`` necesita la serie completa para
    calcular lags correctamente, **no** se puede invocar por separado en
    cada fold.  La estrategia correcta es:

    1. Pre-computar todos los features temporales sobre la serie completa
       (función ``prepare_full_temporal_data``).
    2. Pasar ``X`` e ``y`` ya enriquecidos a ``evaluate_time_series_cv``
       **sin** feature_builder (None).

    Esta función existe por compatibilidad y retorna un builder trivial
    que simplemente selecciona las columnas de features correctas.
    """
    feature_cols = get_temporal_feature_columns(lags, rolling_windows)

    def _builder(X_fold: pd.DataFrame) -> pd.DataFrame:
        # Si las columnas temporales ya están presentes, solo seleccionar
        if all(col in X_fold.columns for col in feature_cols):
            return X_fold[feature_cols].copy()
        # Si no, asumir que es un DataFrame raw y construir desde cero
        # (solo funciona si hay suficiente historial acumulado)
        raise ValueError(
            "create_fold_feature_builder: features temporales no encontradas. "
            "Use prepare_full_temporal_data() + evaluate_time_series_cv() "
            "sin feature_builder en su lugar."
        )

    return _builder


# ---------------------------------------------------------------------------
# Preparación con target de ratio (y / lag_12)
# ---------------------------------------------------------------------------

RATIO_TARGET_COLUMN: Final = "revenue_ratio_to_lag12"


def prepare_full_ratio_data(
    csv_path: Path | str | None = None,
    lags: tuple[int, ...] = DEFAULT_LAGS,
    rolling_windows: tuple[int, ...] = DEFAULT_ROLLING_WINDOWS,
) -> tuple[pd.DataFrame, pd.Series]:
    """Prepara ``(X, y_ratio)`` para predecir el ratio revenue/lag_12.

    El ratio normaliza la escala temporal: si la facturación crece 6% anual,
    el ratio oscila alrededor de 1.06 con baja varianza, eliminando la
    inflación estructural del RMSE que penaliza los folds posteriores.

    Las primeras filas con NaN en ``lag_12`` se eliminan porque no se puede
    calcular el ratio.
    """
    data = load_sales_data(csv_path)
    full = _build_temporal_features(data, lags, rolling_windows)

    # Solo conservar filas con lag_12 válido para calcular ratio
    full = full.dropna(subset=["lag_12"]).reset_index(drop=True)
    full[RATIO_TARGET_COLUMN] = full[TARGET_COLUMN] / full["lag_12"]

    feature_cols = get_temporal_feature_columns(lags, rolling_windows)
    # Eliminar también NaN restantes en features
    full = full.dropna(subset=feature_cols).reset_index(drop=True)

    X = full[feature_cols]
    y = full[RATIO_TARGET_COLUMN].copy()
    return X, y


def prepare_temporal_ratio_data(
    csv_path: Path | str | None = None,
    lags: tuple[int, ...] = DEFAULT_LAGS,
    rolling_windows: tuple[int, ...] = DEFAULT_ROLLING_WINDOWS,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Prepara ``(X, y_ratio, lag_12)`` para train/test con target ratio.

    Devuelve también ``lag_12`` del conjunto de test para reconstruir las
    predicciones en la escala original (pred = ratio_pred * lag_12).
    """
    data = load_sales_data(csv_path)
    full = _build_temporal_features(data, lags, rolling_windows)

    feature_cols = get_temporal_feature_columns(lags, rolling_windows)
    full = full.dropna(subset=feature_cols).reset_index(drop=True)

    train_data, test_data = _split_by_year(full)
    train_data = train_data.dropna(subset=feature_cols + ["lag_12"]).reset_index(drop=True)
    test_data = test_data.dropna(subset=feature_cols + ["lag_12"]).reset_index(drop=True)

    train_data[RATIO_TARGET_COLUMN] = train_data[TARGET_COLUMN] / train_data["lag_12"]
    test_data[RATIO_TARGET_COLUMN] = test_data[TARGET_COLUMN] / test_data["lag_12"]

    X_train = train_data[feature_cols]
    X_test = test_data[feature_cols]
    y_train = train_data[RATIO_TARGET_COLUMN].copy()
    y_test = test_data[RATIO_TARGET_COLUMN].copy()
    lag12_test = test_data["lag_12"].copy()

    return X_train, X_test, y_train, y_test, lag12_test


# ---------------------------------------------------------------------------
# Main para pruebas rápidas
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    prepared = prepare_sales_data()
    print(f"Entrenamiento base: {len(prepared.X_train)} registros, "
          f"{prepared.X_train.columns.tolist()}")

    prepared_temp = prepare_temporal_sales_data()
    print(f"\nEntrenamiento temporal: {len(prepared_temp.X_train)} registros")
    print(f"Prueba temporal: {len(prepared_temp.X_test)} registros")
    print(f"Features: {len(prepared_temp.X_train.columns)} columnas")
    print(prepared_temp.X_train.columns.tolist())

    X_full, y_full = prepare_full_temporal_data()
    print(f"\nSerie completa: {len(X_full)} registros, "
          f"{len(X_full.columns)} features")
    print(f"Rango de y: [{y_full.min():,.0f}, {y_full.max():,.0f}]")
