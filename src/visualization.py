"""Visualizacion ejecutiva de ventas reales y predichas de TrackFlow."""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import matplotlib
import numpy as np
import pandas as pd
from numpy.typing import NDArray

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from data_preparation import DATE_COLUMN, load_sales_data, prepare_sales_data
from model_training import TrainingResult, train_sales_model


DEFAULT_OUTPUT_PATH: Final = Path("outputs/sales_forecast_vs_actual.png")
VARIABILITY_MULTIPLIER: Final = 1.96


@dataclass(frozen=True)
class ForecastSeries:
    """Serie temporal y banda de variabilidad del conjunto de arboles."""

    dates: pd.Series
    actual: pd.Series
    predicted: pd.Series
    lower_bound: pd.Series
    upper_bound: pd.Series


def build_forecast_series(csv_path: Path | str | None = None) -> ForecastSeries:
    """Entrena el bosque y calcula una banda de +/- 1.96 desviaciones estandar."""
    prepared = prepare_sales_data(csv_path)
    training_result: TrainingResult = train_sales_model(csv_path)
    test_values: NDArray[np.float64] = prepared.X_test.to_numpy(dtype=np.float64)

    tree_predictions = np.vstack(
        [tree.predict(test_values) for tree in training_result.model.estimators_]
    )
    prediction_std = tree_predictions.std(axis=0, ddof=1)
    predicted = training_result.predictions

    ordered_data = load_sales_data(csv_path)
    dates = ordered_data.loc[prepared.y_test.index, DATE_COLUMN].copy()
    lower_bound = pd.Series(
        np.maximum(predicted.to_numpy() - VARIABILITY_MULTIPLIER * prediction_std, 0.0),
        index=predicted.index,
        name="lower_bound_eur",
    )
    upper_bound = pd.Series(
        predicted.to_numpy() + VARIABILITY_MULTIPLIER * prediction_std,
        index=predicted.index,
        name="upper_bound_eur",
    )

    if not dates.index.equals(predicted.index):
        raise ValueError("Las fechas y predicciones del periodo de prueba no estan alineadas")

    return ForecastSeries(
        dates=dates,
        actual=prepared.y_test,
        predicted=predicted,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )


def plot_sales_forecast(
    csv_path: Path | str | None = None,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
) -> Path:
    """Genera y guarda la comparativa ejecutiva de los dos anos de prueba."""
    series = build_forecast_series(csv_path)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    figure, axis = plt.subplots(figsize=(13, 7))
    dates = series.dates.to_numpy()
    axis.fill_between(
        dates,
        series.lower_bound.to_numpy(),
        series.upper_bound.to_numpy(),
        color="#E9A23B",
        alpha=0.22,
        linewidth=0,
        label="Variabilidad del bosque (+/- 1.96 sigma)",
    )
    axis.plot(
        dates,
        series.actual.to_numpy(),
        color="#173F5F",
        linewidth=2.6,
        marker="o",
        markersize=4,
        label="Ventas reales",
    )
    axis.plot(
        dates,
        series.predicted.to_numpy(),
        color="#D1495B",
        linewidth=2.3,
        linestyle="--",
        label="Ventas predichas",
    )

    axis.set_title("TrackFlow: ventas reales frente a prediccion", fontsize=17, pad=18)
    axis.set_xlabel("Mes")
    axis.set_ylabel("Ingresos (millones de EUR)")
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1_000_000:.1f}"))
    axis.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%m\n%Y"))
    axis.grid(axis="y", color="#D9DEE3", linewidth=0.8, alpha=0.75)
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False, ncols=3, loc="upper left")
    axis.margins(x=0.01)
    figure.text(
        0.99,
        0.01,
        "Banda basada en la dispersion de las predicciones individuales de 500 arboles.",
        ha="right",
        fontsize=9,
        color="#59636E",
    )
    figure.tight_layout(rect=(0, 0.035, 1, 1))
    figure.savefig(destination, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return destination


if __name__ == "__main__":
    saved_path = plot_sales_forecast()
    print(f"Grafico guardado en: {saved_path.resolve()}")