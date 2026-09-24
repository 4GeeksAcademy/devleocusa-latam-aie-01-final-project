"""Entrenamiento y evaluacion del modelo de ventas de TrackFlow."""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray
from scipy.stats import normaltest
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error

from data_preparation import NUMERIC_FEATURES, PreparedSalesData, prepare_sales_data


RANDOM_STATE: Final = 42
PSI_BUCKETS: Final = 10
PSI_EPSILON: Final = 1e-6


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

    model: RandomForestRegressor
    predictions: pd.Series
    metrics: RegressionMetrics
    feature_importances: pd.Series


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
    )


if __name__ == "__main__":
    result = train_sales_model()
    print(f"MSE: {result.metrics.mse:,.2f}")
    print(f"PSI: {result.metrics.psi:.4f}")
    print(f"Gini normalizado: {result.metrics.gini:.4f}")
    print(f"K2: {result.metrics.k2_score:.4f}")
    print(f"K2 p-value: {result.metrics.k2_p_value:.4f}")
    print("Importancia de variables:")
    print(result.feature_importances.to_string())