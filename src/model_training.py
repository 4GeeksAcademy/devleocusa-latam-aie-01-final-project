"""Entrenamiento y evaluacion del modelo de ventas de TrackFlow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray
from scipy.stats import normaltest
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error

from data_preparation import (
    NUMERIC_FEATURES,
    PreparedSalesData,
    prepare_full_ratio_data,
    prepare_full_temporal_data,
    prepare_sales_data,
    prepare_temporal_sales_data,
)


RANDOM_STATE: Final = 42
PSI_BUCKETS: Final = 10
PSI_EPSILON: Final = 1e-6

# Tipo para los modelos soportados (RandomForest, XGBoost, LightGBM)
ModelType = Any


@dataclass(frozen=True)
class RegressionMetrics:
    """Metricas de precision, estabilidad, ranking y residuos."""

    mse: float
    psi: float
    gini: float
    k2_score: float
    k2_p_value: float


@dataclass(frozen=True)
class TrainingResult:
    """Modelo entrenado, predicciones de prueba y resultados de evaluacion."""

    model: ModelType
    predictions: pd.Series
    metrics: RegressionMetrics
    feature_importances: pd.Series
    model_name: str = "unknown"


def _as_finite_array(values: ArrayLike, name: str) -> NDArray[np.float64]:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    if array.size == 0:
        raise ValueError(f"{name} no puede estar vacio")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contiene valores no finitos")
    return array


def population_stability_index(
    expected: ArrayLike,
    actual: ArrayLike,
    buckets: int = PSI_BUCKETS,
) -> float:
    """Calcula PSI usando cuantiles de la distribucion historica como cortes."""
    expected_array = _as_finite_array(expected, "expected")
    actual_array = _as_finite_array(actual, "actual")
    if buckets < 2:
        raise ValueError("PSI requiere al menos dos intervalos")

    quantiles = np.linspace(0.0, 1.0, buckets + 1)
    inner_edges = np.unique(np.quantile(expected_array, quantiles)[1:-1])
    edges = np.concatenate(([-np.inf], inner_edges, [np.inf]))
    expected_counts, _ = np.histogram(expected_array, bins=edges)
    actual_counts, _ = np.histogram(actual_array, bins=edges)

    expected_ratio = np.clip(expected_counts / expected_array.size, PSI_EPSILON, None)
    actual_ratio = np.clip(actual_counts / actual_array.size, PSI_EPSILON, None)
    return float(np.sum((actual_ratio - expected_ratio) * np.log(actual_ratio / expected_ratio)))


def _gini_coefficient(actual: NDArray[np.float64], score: NDArray[np.float64]) -> float:
    order = np.lexsort((np.arange(actual.size), -score))
    ordered_actual = actual[order]
    total = ordered_actual.sum()
    if np.isclose(total, 0.0):
        raise ValueError("Gini no esta definido cuando el objetivo suma cero")

    cumulative = np.cumsum(ordered_actual)
    return float((cumulative.sum() / total - (actual.size + 1) / 2.0) / actual.size)


def normalized_gini(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    """Mide la calidad del ranking y la normaliza contra el orden perfecto."""
    actual = _as_finite_array(y_true, "y_true")
    predicted = _as_finite_array(y_pred, "y_pred")
    if actual.size != predicted.size:
        raise ValueError("y_true e y_pred deben tener la misma longitud")

    perfect_gini = _gini_coefficient(actual, actual)
    if np.isclose(perfect_gini, 0.0):
        return 0.0
    return float(_gini_coefficient(actual, predicted) / perfect_gini)


def evaluate_predictions(
    y_train: ArrayLike,
    y_test: ArrayLike,
    predictions: ArrayLike,
) -> RegressionMetrics:
    """Evalua las predicciones futuras sin reentrenar ni reajustar el modelo."""
    train_values = _as_finite_array(y_train, "y_train")
    test_values = _as_finite_array(y_test, "y_test")
    predicted_values = _as_finite_array(predictions, "predictions")
    if test_values.size != predicted_values.size:
        raise ValueError("y_test y predictions deben tener la misma longitud")
    if test_values.size < 8:
        raise ValueError("K2 requiere al menos ocho residuos")

    residuals = test_values - predicted_values
    k2_result = normaltest(residuals)
    return RegressionMetrics(
        mse=float(mean_squared_error(test_values, predicted_values)),
        psi=population_stability_index(train_values, predicted_values),
        gini=normalized_gini(test_values, predicted_values),
        k2_score=float(k2_result.statistic),
        k2_p_value=float(k2_result.pvalue),
    )


def train_sales_model(
    csv_path: Path | str | None = None,
    *,
    n_estimators: int = 500,
) -> TrainingResult:
    """Entrena con ocho anos y evalua exclusivamente los dos anos futuros."""
    prepared: PreparedSalesData = prepare_sales_data(csv_path)
    model = RandomForestRegressor(
        n_estimators=n_estimators,
        random_state=RANDOM_STATE,
        n_jobs=-1,
        max_depth=8,
        min_samples_leaf=3,
    )
    model.fit(prepared.X_train, prepared.y_train)

    predicted_values = model.predict(prepared.X_test)
    predictions = pd.Series(
        predicted_values,
        index=prepared.y_test.index,
        name="predicted_revenue_eur",
    )
    metrics = evaluate_predictions(prepared.y_train, prepared.y_test, predictions)
    feature_importances = pd.Series(
        model.feature_importances_,
        index=NUMERIC_FEATURES,
        name="importance",
    ).sort_values(ascending=False)

    return TrainingResult(
        model=model,
        predictions=predictions,
        metrics=metrics,
        feature_importances=feature_importances,
        model_name="RandomForest",
    )


# ---------------------------------------------------------------------------
# Modelos de Gradient Boosting
# ---------------------------------------------------------------------------

def _extract_feature_importances(
    model: ModelType,
    feature_names: list[str] | pd.Index,
) -> pd.Series:
    """Extrae importancia de features de cualquier modelo compatible."""
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    elif hasattr(model, "get_booster"):
        # XGBoost: usar importancia de tipo 'gain'
        booster = model.get_booster()
        score = booster.get_score(importance_type="gain")
        importances = np.zeros(len(feature_names))
        for key, value in score.items():
            # keys son "f0", "f1", etc.
            idx = int(key.replace("f", ""))
            if idx < len(importances):
                importances[idx] = value
    elif hasattr(model, "booster_"):
        # LightGBM
        importances = model.feature_importances_
    else:
        importances = np.ones(len(feature_names)) / len(feature_names)

    return pd.Series(importances, index=feature_names, name="importance").sort_values(
        ascending=False
    )


def train_xgboost_sales_model(
    csv_path: Path | str | None = None,
    *,
    use_temporal_features: bool = False,
    n_estimators: int = 500,
    max_depth: int = 6,
    learning_rate: float = 0.05,
    subsample: float = 0.8,
    colsample_bytree: float = 0.8,
    reg_alpha: float = 0.1,
    reg_lambda: float = 1.0,
    min_child_weight: int = 5,
) -> TrainingResult:
    """Entrena XGBoost con features temporales y evalua en el futuro."""
    try:
        from xgboost import XGBRegressor
    except ImportError:
        raise ImportError("XGBoost no esta instalado. Ejecute: pip install xgboost")

    if use_temporal_features:
        prepared = prepare_temporal_sales_data(csv_path)
        feature_cols = list(prepared.X_train.columns)
    else:
        prepared = prepare_sales_data(csv_path)
        feature_cols = list(NUMERIC_FEATURES)

    model = XGBRegressor(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=subsample,
        colsample_bytree=colsample_bytree,
        reg_alpha=reg_alpha,
        reg_lambda=reg_lambda,
        min_child_weight=min_child_weight,
        random_state=RANDOM_STATE,
        n_jobs=-1,
        verbosity=0,
    )
    model.fit(prepared.X_train, prepared.y_train)

    predicted_values = model.predict(prepared.X_test)
    predictions = pd.Series(
        predicted_values,
        index=prepared.y_test.index,
        name="predicted_revenue_eur",
    )
    metrics = evaluate_predictions(prepared.y_train, prepared.y_test, predictions)
    feature_importances = _extract_feature_importances(model, feature_cols)

    return TrainingResult(
        model=model,
        predictions=predictions,
        metrics=metrics,
        feature_importances=feature_importances,
        model_name="XGBoost",
    )


def train_lightgbm_sales_model(
    csv_path: Path | str | None = None,
    *,
    use_temporal_features: bool = False,
    n_estimators: int = 500,
    max_depth: int = 6,
    learning_rate: float = 0.05,
    subsample: float = 0.8,
    colsample_bytree: float = 0.8,
    reg_alpha: float = 0.1,
    reg_lambda: float = 1.0,
    min_child_samples: int = 5,
) -> TrainingResult:
    """Entrena LightGBM con features temporales y evalua en el futuro."""
    try:
        from lightgbm import LGBMRegressor
    except ImportError:
        raise ImportError("LightGBM no esta instalado. Ejecute: pip install lightgbm")

    if use_temporal_features:
        prepared = prepare_temporal_sales_data(csv_path)
        feature_cols = list(prepared.X_train.columns)
    else:
        prepared = prepare_sales_data(csv_path)
        feature_cols = list(NUMERIC_FEATURES)

    model = LGBMRegressor(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=subsample,
        colsample_bytree=colsample_bytree,
        reg_alpha=reg_alpha,
        reg_lambda=reg_lambda,
        min_child_samples=min_child_samples,
        random_state=RANDOM_STATE,
        n_jobs=-1,
        verbose=-1,
    )
    model.fit(prepared.X_train, prepared.y_train)

    predicted_values = model.predict(prepared.X_test)
    predictions = pd.Series(
        predicted_values,
        index=prepared.y_test.index,
        name="predicted_revenue_eur",
    )
    metrics = evaluate_predictions(prepared.y_train, prepared.y_test, predictions)
    feature_importances = _extract_feature_importances(model, feature_cols)

    return TrainingResult(
        model=model,
        predictions=predictions,
        metrics=metrics,
        feature_importances=feature_importances,
        model_name="LightGBM",
    )


# ---------------------------------------------------------------------------
# Entrenamiento con target ratio (y / lag_12)
# ---------------------------------------------------------------------------

def train_ratio_model(
    csv_path: Path | str | None = None,
    *,
    model_type: str = "xgboost",
) -> TrainingResult:
    """Entrena un modelo predictivo del ratio revenue/lag_12.

    El ratio normaliza la escala temporal y elimina la inflación
    estructural del RMSE.  La predicción final se obtiene:
        ``pred_ratio * lag_12_test``

    ``model_type``: "xgboost", "lightgbm" o "random_forest".
    """
    from data_preparation import prepare_temporal_ratio_data

    X_train, X_test, y_train, y_test, lag12_test = prepare_temporal_ratio_data(csv_path)
    feature_cols = list(X_train.columns)

    if model_type == "xgboost":
        try:
            from xgboost import XGBRegressor
        except ImportError:
            raise ImportError("XGBoost no instalado")
        model = XGBRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.01,
            subsample=0.7, colsample_bytree=0.6,
            reg_alpha=5.0, reg_lambda=10.0, min_child_weight=20,
            random_state=RANDOM_STATE, n_jobs=-1, verbosity=0,
        )
        model_name = "XGBoost-Ratio"
    elif model_type == "lightgbm":
        try:
            from lightgbm import LGBMRegressor
        except ImportError:
            raise ImportError("LightGBM no instalado")
        model = LGBMRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.01,
            subsample=0.7, colsample_bytree=0.6,
            reg_alpha=5.0, reg_lambda=10.0, min_child_samples=20,
            random_state=RANDOM_STATE, n_jobs=-1, verbose=-1,
        )
        model_name = "LightGBM-Ratio"
    elif model_type == "random_forest":
        model = RandomForestRegressor(
            n_estimators=300, max_depth=4, min_samples_leaf=10,
            random_state=RANDOM_STATE, n_jobs=-1,
        )
        model_name = "RF-Ratio"
    else:
        raise ValueError(f"model_type desconocido: {model_type}")

    model.fit(X_train, y_train)

    # Predicción en escala original: ratio * lag_12
    predicted_ratio = model.predict(X_test)
    predicted_values = predicted_ratio * lag12_test.values
    actual_values = y_test.values * lag12_test.values

    predictions = pd.Series(
        predicted_values,
        index=y_test.index,
        name="predicted_revenue_eur",
    )

    # Evaluar en escala original
    metrics = evaluate_predictions(
        y_train.values * 1,  # dummy (no directamente comparable)
        actual_values,
        predicted_values,
    )
    feature_importances = _extract_feature_importances(model, feature_cols)

    return TrainingResult(
        model=model,
        predictions=predictions,
        metrics=metrics,
        feature_importances=feature_importances,
        model_name=model_name,
    )


# ---------------------------------------------------------------------------
# Comparación de modelos
# ---------------------------------------------------------------------------

def compare_models(
    csv_path: Path | str | None = None,
) -> list[TrainingResult]:
    """Entrena todos los modelos (base + temporales + ratio) y retorna resultados."""
    results: list[TrainingResult] = []

    # 1. RandomForest base (2 features)
    print("Entrenando RandomForest (base)...")
    results.append(train_sales_model(csv_path))

    # 2. XGBoost base (2 features)
    print("Entrenando XGBoost (base)...")
    results.append(train_xgboost_sales_model(csv_path, use_temporal_features=False))

    # 3. XGBoost temporal (36 features)
    print("Entrenando XGBoost (temporal)...")
    results.append(train_xgboost_sales_model(csv_path, use_temporal_features=True))

    # 4. LightGBM base (2 features)
    print("Entrenando LightGBM (base)...")
    results.append(train_lightgbm_sales_model(csv_path, use_temporal_features=False))

    # 5. LightGBM temporal (36 features)
    print("Entrenando LightGBM (temporal)...")
    results.append(train_lightgbm_sales_model(csv_path, use_temporal_features=True))

    # 6. Modelos con ratio target
    print("Entrenando XGBoost-Ratio...")
    results.append(train_ratio_model(csv_path, model_type="xgboost"))

    print("Entrenando LightGBM-Ratio...")
    results.append(train_ratio_model(csv_path, model_type="lightgbm"))

    print("Entrenando RF-Ratio...")
    results.append(train_ratio_model(csv_path, model_type="random_forest"))

    return results


if __name__ == "__main__":
    results = compare_models()
    print("\n" + "=" * 80)
    print("COMPARACIÓN DE MODELOS")
    print("=" * 80)
    for r in results:
        print(f"\n--- {r.model_name} ---")
        print(f"  MSE:   {r.metrics.mse:>15,.2f}")
        print(f"  PSI:   {r.metrics.psi:>15.4f}")
        print(f"  Gini:  {r.metrics.gini:>15.4f}")
        print(f"  K2:    {r.metrics.k2_score:>15.4f} (p={r.metrics.k2_p_value:.4f})")
        print(f"  Top features:")
        for feat, imp in r.feature_importances.head(5).items():
            print(f"    {feat}: {imp:.4f}")