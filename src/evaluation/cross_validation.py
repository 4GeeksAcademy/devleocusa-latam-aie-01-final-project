"""Evaluacion de modelos sobre particiones temporales sin fuga de datos."""

from __future__ import annotations

from typing import Callable, Protocol, TypedDict, TypeVar, cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.base import clone
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit


FeatureMatrix = pd.DataFrame | NDArray[np.generic]
TargetVector = pd.Series | NDArray[np.generic]
FeatureBuilder = Callable[[FeatureMatrix], FeatureMatrix]


class Regressor(Protocol):
    """Contrato minimo requerido para evaluar un modelo de regresion."""

    def fit(self, X: FeatureMatrix, y: TargetVector) -> Regressor: ...

    def predict(self, X: FeatureMatrix) -> NDArray[np.generic]: ...


RegressorT = TypeVar("RegressorT", bound=Regressor)


class TimeSeriesCVMetrics(TypedDict):
    """Resumen agregado de las metricas calculadas en todos los folds."""

    train_mae_mean: float
    train_mae_std: float
    validation_mae_mean: float
    validation_mae_std: float
    train_rmse_mean: float
    train_rmse_std: float
    validation_rmse_mean: float
    validation_rmse_std: float


def _take_rows(
    data: FeatureMatrix | TargetVector,
    indices: NDArray[np.int64],
) -> FeatureMatrix | TargetVector:
    if isinstance(data, (pd.DataFrame, pd.Series)):
        return data.iloc[indices]
    return data[indices]


def _validate_inputs(X: FeatureMatrix, y: TargetVector, n_splits: int) -> None:
    if len(X) != len(y):
        raise ValueError("X e y deben tener la misma cantidad de observaciones")
    if n_splits < 2:
        raise ValueError("n_splits debe ser al menos 2")
    if len(X) <= n_splits:
        raise ValueError("El numero de observaciones debe ser mayor que n_splits")
    if isinstance(X, pd.DataFrame) and not X.index.is_monotonic_increasing:
        raise ValueError("X debe estar ordenado cronologicamente")
    if isinstance(y, pd.Series) and not y.index.is_monotonic_increasing:
        raise ValueError("y debe estar ordenado cronologicamente")
    if isinstance(X, pd.DataFrame) and isinstance(y, pd.Series) and not X.index.equals(y.index):
        raise ValueError("Los indices de X e y deben estar alineados")


def evaluate_time_series_cv(
    model: RegressorT,
    X: FeatureMatrix,
    y: TargetVector,
    n_splits: int = 5,
    feature_builder: FeatureBuilder | None = None,
) -> TimeSeriesCVMetrics:
    """Calcula metricas temporales aislando cualquier feature derivada por fold.

    Si se proporciona ``feature_builder``, recibe exclusivamente las filas del
    conjunto correspondiente; por tanto, un calculo de lag o rolling no puede
    consultar filas de validacion al construir el entrenamiento.
    """
    _validate_inputs(X, y, n_splits)
    splitter = TimeSeriesSplit(n_splits=n_splits)
    fold_metrics: dict[str, list[float]] = {
        "train_mae": [],
        "validation_mae": [],
        "train_rmse": [],
        "validation_rmse": [],
    }

    for train_indices, validation_indices in splitter.split(X):
        if train_indices[-1] >= validation_indices[0]:
            raise RuntimeError("La particion temporal contiene solapamiento")

        X_train_raw = _take_rows(X, train_indices)
        X_validation_raw = _take_rows(X, validation_indices)
        y_train = _take_rows(y, train_indices)
        y_validation = _take_rows(y, validation_indices)

        if feature_builder is None:
            X_train = X_train_raw
            X_validation = X_validation_raw
        else:
            X_train = feature_builder(X_train_raw)
            X_validation = feature_builder(X_validation_raw)
            if len(X_train) != len(y_train) or len(X_validation) != len(y_validation):
                raise ValueError("feature_builder debe conservar la cantidad de filas")

        fold_model = cast(Regressor, clone(model))
        fold_model.fit(X_train, y_train)
        train_predictions = fold_model.predict(X_train)
        validation_predictions = fold_model.predict(X_validation)

        fold_metrics["train_mae"].append(float(mean_absolute_error(y_train, train_predictions)))
        fold_metrics["validation_mae"].append(
            float(mean_absolute_error(y_validation, validation_predictions))
        )
        fold_metrics["train_rmse"].append(
            float(np.sqrt(mean_squared_error(y_train, train_predictions)))
        )
        fold_metrics["validation_rmse"].append(
            float(np.sqrt(mean_squared_error(y_validation, validation_predictions)))
        )

    return {
        "train_mae_mean": float(np.mean(fold_metrics["train_mae"])),
        "train_mae_std": float(np.std(fold_metrics["train_mae"])),
        "validation_mae_mean": float(np.mean(fold_metrics["validation_mae"])),
        "validation_mae_std": float(np.std(fold_metrics["validation_mae"])),
        "train_rmse_mean": float(np.mean(fold_metrics["train_rmse"])),
        "train_rmse_std": float(np.std(fold_metrics["train_rmse"])),
        "validation_rmse_mean": float(np.mean(fold_metrics["validation_rmse"])),
        "validation_rmse_std": float(np.std(fold_metrics["validation_rmse"])),
    }