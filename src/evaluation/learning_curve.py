"""Generacion de curvas de aprendizaje para modelos de regresion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import matplotlib
import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.base import BaseEstimator
from sklearn.model_selection import BaseCrossValidator, learning_curve

matplotlib.use("Agg")
import matplotlib.pyplot as plt


DEFAULT_OUTPUT_PATH: Final[Path] = Path("data/eval/learning_curve.png")
LEARNING_CURVE_SIZES: Final[NDArray[np.float64]] = np.array(
    [0.10, 0.25, 0.50, 0.75, 1.00],
    dtype=np.float64,
)


@dataclass(frozen=True)
class LearningCurveResult:
    """Valores agregados que sustentan la interpretacion de la curva."""

    train_sizes: NDArray[np.int64]
    train_rmse_mean: NDArray[np.float64]
    train_rmse_std: NDArray[np.float64]
    validation_rmse_mean: NDArray[np.float64]
    validation_rmse_std: NDArray[np.float64]


def calculate_learning_curve(
    model: BaseEstimator,
    X: pd.DataFrame,
    y: pd.Series,
    cv_strategy: BaseCrossValidator,
) -> LearningCurveResult:
    """Calcula los puntos RMSE sin producir efectos de graficacion."""
    train_sizes, train_scores, validation_scores = learning_curve(
        estimator=model,
        X=X,
        y=y,
        cv=cv_strategy,
        train_sizes=LEARNING_CURVE_SIZES,
        scoring="neg_root_mean_squared_error",
        shuffle=False,
    )

    train_rmse = -train_scores
    validation_rmse = -validation_scores
    return LearningCurveResult(
        train_sizes=train_sizes,
        train_rmse_mean=train_rmse.mean(axis=1),
        train_rmse_std=train_rmse.std(axis=1),
        validation_rmse_mean=validation_rmse.mean(axis=1),
        validation_rmse_std=validation_rmse.std(axis=1),
    )


def plot_and_save_learning_curve(
    model: BaseEstimator,
    X: pd.DataFrame,
    y: pd.Series,
    cv_strategy: BaseCrossValidator,
) -> Path:
    """Genera una curva RMSE temporal y la guarda en disco."""
    destination = DEFAULT_OUTPUT_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)

    curve = calculate_learning_curve(model, X, y, cv_strategy)

    figure, axis = plt.subplots(figsize=(10, 6))
    try:
        axis.plot(curve.train_sizes, curve.train_rmse_mean, marker="o", label="Entrenamiento")
        axis.fill_between(
            curve.train_sizes,
            curve.train_rmse_mean - curve.train_rmse_std,
            curve.train_rmse_mean + curve.train_rmse_std,
            alpha=0.2,
        )
        axis.plot(
            curve.train_sizes,
            curve.validation_rmse_mean,
            marker="o",
            label="Validacion",
        )
        axis.fill_between(
            curve.train_sizes,
            curve.validation_rmse_mean - curve.validation_rmse_std,
            curve.validation_rmse_mean + curve.validation_rmse_std,
            alpha=0.2,
        )
        axis.set_title("Curva de aprendizaje")
        axis.set_xlabel("Tamano del conjunto de entrenamiento")
        axis.set_ylabel("RMSE")
        axis.legend()
        axis.grid(True, alpha=0.25)
        figure.tight_layout()
        figure.savefig(destination, dpi=150)
    finally:
        plt.close(figure)

    return destination