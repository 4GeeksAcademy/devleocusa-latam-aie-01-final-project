"""Pruebas de integridad temporal para la validacion cruzada."""

from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import TimeSeriesSplit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from evaluation.cross_validation import evaluate_time_series_cv


def test_time_series_cv_never_leaks_future_observations() -> None:
    """Garantiza que cada fold entrena estrictamente antes de validar."""
    timestamps = pd.date_range("2015-01-01", periods=120, freq="MS")
    X = pd.DataFrame(
        {"time_index": np.arange(120, dtype=float)},
        index=timestamps,
    )
    y = pd.Series(
        10.0 + 2.0 * X["time_index"].to_numpy(),
        index=timestamps,
        name="target",
    )
    cv_strategy = TimeSeriesSplit(n_splits=5)

    metrics = evaluate_time_series_cv(LinearRegression(), X, y, n_splits=5)

    assert np.isfinite(list(metrics.values())).all()
    for fold_number, (train_indices, validation_indices) in enumerate(
        cv_strategy.split(X),
        start=1,
    ):
        train_times = X.index[train_indices].to_numpy()
        validation_times = X.index[validation_indices].to_numpy()

        assert train_times.max() < validation_times.min(), (
            f"Fuga temporal en fold {fold_number}: "
            f"max(train)={train_times.max()} no es menor que "
            f"min(validation)={validation_times.min()}"
        )


def test_feature_builder_receives_only_one_fold_at_a_time() -> None:
    """Evita que features derivadas consulten filas de otro conjunto."""
    timestamps = pd.date_range("2015-01-01", periods=120, freq="MS")
    X = pd.DataFrame(
        {"time_index": np.arange(120, dtype=float)},
        index=timestamps,
    )
    y = pd.Series(10.0 + X["time_index"].to_numpy(), index=timestamps)
    observed_ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    def record_feature_input(data: pd.DataFrame) -> pd.DataFrame:
        observed_ranges.append((data.index.min(), data.index.max()))
        return data

    evaluate_time_series_cv(
        LinearRegression(),
        X,
        y,
        n_splits=5,
        feature_builder=record_feature_input,
    )

    assert len(observed_ranges) == 10
    for train_range, validation_range in zip(
        observed_ranges[::2], observed_ranges[1::2]
    ):
        assert train_range[1] < validation_range[0], (
            "El feature_builder recibio un rango de entrenamiento que alcanza "
            f"la validacion: max(train)={train_range[1]}, "
            f"min(validation)={validation_range[0]}"
        )