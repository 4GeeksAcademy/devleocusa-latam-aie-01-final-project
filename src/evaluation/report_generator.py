"""Genera el reporte tecnico de evaluacion con contexto operativo de TrackFlow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import pandas as pd
from sklearn.base import BaseEstimator
from sklearn.model_selection import BaseCrossValidator

from evaluation.cross_validation import TimeSeriesCVMetrics, evaluate_time_series_cv
from evaluation.learning_curve import LearningCurveResult, calculate_learning_curve


DEFAULT_REPORT_PATH: Final[Path] = Path("data/eval/evaluation_report.md")
OVERFITTING_GAP_THRESHOLD: Final[float] = 0.20
UNDERFITTING_GAP_THRESHOLD: Final[float] = -0.10

FitDiagnosis = Literal["underfitting", "overfitting", "bien ajustado"]


@dataclass(frozen=True)
class FitAssessment:
    """Diagnostico reproducible a partir de la brecha RMSE temporal."""

    diagnosis: FitDiagnosis
    rmse_gap: float
    relative_gap: float
    recommendation: str
    source: str


def assess_fit(
    metrics: TimeSeriesCVMetrics,
    curve: LearningCurveResult | None = None,
) -> FitAssessment:
    """Clasifica el ajuste usando la brecha del ultimo punto de la curva."""
    if curve is None:
        train_rmse = metrics["train_rmse_mean"]
        validation_rmse = metrics["validation_rmse_mean"]
        source = "la media de la validacion cruzada temporal"
    else:
        train_rmse = float(curve.train_rmse_mean[-1])
        validation_rmse = float(curve.validation_rmse_mean[-1])
        source = "el último punto de la curva de aprendizaje"

    rmse_gap = validation_rmse - train_rmse
    denominator = max(validation_rmse, 1e-12)
    relative_gap = rmse_gap / denominator

    if relative_gap >= OVERFITTING_GAP_THRESHOLD:
        return FitAssessment(
            diagnosis="overfitting",
            rmse_gap=rmse_gap,
            relative_gap=relative_gap,
            recommendation=(
                "Aplicar regularizacion al bosque: reducir la profundidad maxima "
                "(`max_depth`), aumentar `min_samples_leaf` y validar la mejora "
                "con la misma particion temporal."
            ),
            source=source,
        )
    if relative_gap <= UNDERFITTING_GAP_THRESHOLD:
        return FitAssessment(
            diagnosis="underfitting",
            rmse_gap=rmse_gap,
            relative_gap=relative_gap,
            recommendation=(
                "Revisar y enriquecer las features temporales y operativas, "
                "incluyendo estacionalidad y rezagos causales; despues repetir "
                "la validacion sin usar informacion futura."
            ),
            source=source,
        )
    return FitAssessment(
        diagnosis="bien ajustado",
        rmse_gap=rmse_gap,
        relative_gap=relative_gap,
        recommendation=(
            "Mantener la complejidad actual y monitorizar los picos de demanda "
            "con la misma validacion temporal antes de modificar el modelo."
        ),
        source=source,
    )


def _format_metric(value: float) -> str:
    return f"{value:,.2f}"


def build_report_content(
    metrics: TimeSeriesCVMetrics,
    assessment: FitAssessment,
    curve: LearningCurveResult | None = None,
) -> str:
    """Construye el contenido Markdown del reporte de evaluacion."""
    curve_evidence = ""
    if curve is not None:
        curve_evidence = f"""
## Evidencia de la curva de aprendizaje

El último punto usa **{int(curve.train_sizes[-1])} observaciones**. Su RMSE de
entrenamiento es **{_format_metric(float(curve.train_rmse_mean[-1]))} EUR** y el
RMSE de validación es **{_format_metric(float(curve.validation_rmse_mean[-1]))}
EUR**, con una brecha de **{assessment.relative_gap:.2%}**. Esta diferencia sustenta
el diagnóstico de **{assessment.diagnosis}** y permite distinguir una brecha real
de ajuste de una variación aislada de un fold.
"""
    return f"""# Reporte técnico de evaluación del modelo

## Resumen ejecutivo

La validación cruzada respeta la secuencia temporal: cada fold entrena con meses
anteriores y valida con meses posteriores, sin barajar observaciones. El modelo se
diagnostica como **{assessment.diagnosis}** según la brecha de RMSE entre ambos
conjuntos, calculada a partir de {assessment.source}.

La brecha absoluta es de **{_format_metric(assessment.rmse_gap)} EUR** y la brecha
relativa es de **{assessment.relative_gap:.2%}** respecto al RMSE de validación.
El umbral aplicado considera overfitting desde el 20% de brecha positiva y
underfitting desde el -10%; entre ambos rangos se considera un ajuste equilibrado.

## Métricas de validación temporal

| Métrica | Media | Desviación estándar |
| --- | ---: | ---: |
| MAE de entrenamiento (EUR) | {_format_metric(metrics["train_mae_mean"])} | {_format_metric(metrics["train_mae_std"])} |
| MAE de validación (EUR) | {_format_metric(metrics["validation_mae_mean"])} | {_format_metric(metrics["validation_mae_std"])} |
| RMSE de entrenamiento (EUR) | {_format_metric(metrics["train_rmse_mean"])} | {_format_metric(metrics["train_rmse_std"])} |
| RMSE de validación (EUR) | {_format_metric(metrics["validation_rmse_mean"])} | {_format_metric(metrics["validation_rmse_std"])} |
{curve_evidence}

## Por qué RMSE es la métrica principal

La operación tiene un coste asimétrico: subestimar la demanda cuesta mucho más que
sobreestimarla. RMSE es la métrica principal porque eleva cada error al cuadrado;
por tanto, un pico inesperado que el modelo subestima recibe una penalización
desproporcionada frente a errores ordinarios. Esto hace visibles precisamente los
fallos que pueden comprometer la capacidad operativa, aunque MAE se conserva como
referencia de error típico.

## Impacto de subestimar la demanda

Los falsos negativos pueden provocar:

- Falta de operarios en los almacenes de Los Ángeles o Zaragoza supervisados por
  Ana Whitfield.
- Pérdida de ventanas de recogida de UPS, FedEx, MRW y SEUR gestionadas por Carlos
  Vega.
- Saturación del equipo de Atención al Cliente de Valentina Cruz.
- Alto riesgo de perder renovaciones de contratos anuales gestionadas por el equipo
  de Miguel Torres.

Por este motivo, la brecha de RMSE no es solo una diferencia estadística: si la
curva de validación permanece por encima de la de entrenamiento en los meses con
picos, el modelo está ocultando el riesgo operativo más caro.

## Impacto de sobreestimar la demanda

Los falsos positivos generan personal y recursos ociosos en los almacenes. Es un
sobrecosto financiero temporal, pero no deteriora la relación B2B ni provoca la
pérdida directa de ventanas, capacidad de atención o renovaciones.

## Acción correctiva

**{assessment.recommendation}** La decisión debe validarse nuevamente con RMSE
temporal: una mejora promedio que solo reduzca errores pequeños no es suficiente si
empeora los picos, porque el término cuadrático del RMSE volvería a penalizar esos
fallos de alta severidad.
"""


def generate_evaluation_report(
    model: BaseEstimator,
    X: pd.DataFrame,
    y: pd.Series,
    cv_strategy: BaseCrossValidator,
    output_path: Path | str = DEFAULT_REPORT_PATH,
) -> Path:
    """Evalua el modelo y escribe el reporte tecnico en Markdown."""
    metrics = evaluate_time_series_cv(model, X, y, n_splits=cv_strategy.n_splits)
    curve = calculate_learning_curve(model, X, y, cv_strategy)
    assessment = assess_fit(metrics, curve)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        build_report_content(metrics, assessment, curve),
        encoding="utf-8",
    )
    return destination