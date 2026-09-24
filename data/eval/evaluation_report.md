# Reporte técnico de evaluación del modelo

## Resumen ejecutivo

La validación cruzada respeta la secuencia temporal: cada fold entrena con meses
anteriores y valida con meses posteriores, sin barajar observaciones. El modelo se
diagnostica como **overfitting** según la brecha de RMSE entre ambos
conjuntos, calculada a partir de el último punto de la curva de aprendizaje.

La brecha absoluta es de **128,011.82 EUR** y la brecha
relativa es de **88.21%** respecto al RMSE de validación.
El umbral aplicado considera overfitting desde el 20% de brecha positiva y
underfitting desde el -10%; entre ambos rangos se considera un ajuste equilibrado.

## Métricas de validación temporal

| Métrica | Media | Desviación estándar |
| --- | ---: | ---: |
| MAE de entrenamiento (EUR) | 8,565.74 | 2,516.69 |
| MAE de validación (EUR) | 43,714.13 | 12,658.58 |
| RMSE de entrenamiento (EUR) | 11,242.08 | 3,033.53 |
| RMSE de validación (EUR) | 58,968.29 | 19,096.43 |

## Evidencia de la curva de aprendizaje

El último punto usa **16 observaciones**. Su RMSE de
entrenamiento es **17,108.10 EUR** y el
RMSE de validación es **145,119.91
EUR**, con una brecha de **88.21%**. Esta diferencia sustenta
el diagnóstico de **overfitting** y permite distinguir una brecha real
de ajuste de una variación aislada de un fold.


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

**Aplicar regularizacion al bosque: reducir la profundidad maxima (`max_depth`), aumentar `min_samples_leaf` y validar la mejora con la misma particion temporal.** La decisión debe validarse nuevamente con RMSE
temporal: una mejora promedio que solo reduzca errores pequeños no es suficiente si
empeora los picos, porque el término cuadrático del RMSE volvería a penalizar esos
fallos de alta severidad.
