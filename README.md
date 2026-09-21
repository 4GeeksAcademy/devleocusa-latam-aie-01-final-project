# AI Engineering Company Project — Student Template

[![4Geeks Academy](https://img.shields.io/badge/4Geeks-Academy-blue)](https://4geeksacademy.com)
[![AI Engineering](https://img.shields.io/badge/track-AI%20Engineering-green)](https://4geeksacademy.com/es/programas-de-carrera/ingenieria-ia)

_Base template for transversal projects in the AI Engineering Career Program — 4Geeks Academy._

> _Instrucciones disponibles en español en [README.es.md](./README.es.md)._

---

## Purpose

This repository is the **starter template** for transversal projects. You will work on real company scenarios (Brasaland, TrackFlow, Nexova), building deliverables that map to course milestones (Web, Programming, Backend, Telemetry, RAG, Agents, Workflows, Real-time).

- Create a template from this repository.
- Replace the placeholder `CONTEXT.md` with your assigned company context.
- Use `skills/` and the directory-level `README.md` files as working guidance.

---

## Current status of the template

The repository currently provides a **base folder structure and documentation skeleton**. It does not include runnable apps or global scripts yet.

- `CONTEXT.md` is a placeholder and must be replaced with your assigned company context.
- There is no root `AGENTS.md` yet.
- Shared package metadata exists in `packages/shared/package.json` (`@repo/shared-types`), but no workspace runner is configured at root.

---

## Repository structure

```text
ai-engineering-company-project-template/
├── README.md
├── README.es.md
├── CONTEXT.md                # Placeholder to be replaced with assigned context
├── agents/                   # Agent patterns/templates and tools docs
├── apps/                     # Product apps (web, APIs, dashboards)
├── data/                     # raw, process, pipelines, eval
├── docs/                     # Project and architecture documentation
├── packages/
│   └── shared/               # Shared package (@repo/shared-types)
├── scripts/                  # Script conventions/documentation
├── shared/                   # Shared assets/conventions at repo level
├── skills/                   # Reusable agent skills
└── workflows/                # Automation/orchestration documentation
```

---

## How to start

1. **Use this repository as a template** and create your own project repo.
2. **Clone** your repository (or open it in Codespaces).
3. **Replace** `CONTEXT.md` with the full context for your assigned company.
4. **Review** each top-level folder `README.md` to understand intended responsibilities (`apps/`, `data/`, `skills/`, etc.).
5. **Start implementing** milestone deliverables in `apps/`, reusing `packages/shared/` and `data/` as needed.

### TypeScript validation

For TypeScript consistency checks in the shared package, run:

- `npm run typecheck --prefix packages/shared`

This executes `tsc --noEmit` and validates types without generating build artifacts.

### Modelo de prediccion de ventas de TrackFlow

El modelo utiliza **Random Forest** porque el equipo de Finanzas necesita una
solucion estable y explicable. Su importancia de variables permite mostrar si
el pronostico depende principalmente del volumen de envios o del ingreso medio
por envio. Frente a XGBoost, evita una optimizacion de hiperparametros mas
compleja que no se justifica con solo 120 observaciones mensuales.

La preparacion respeta estrictamente el tiempo: el modelo se ajusta solo con los
ocho primeros anos (96 meses) y se evalua con los dos anos mas recientes (24
meses). El imputador y el escalador tambien se ajustan exclusivamente con el
periodo de entrenamiento, de modo que ninguna informacion futura interviene en
el aprendizaje.

Las metricas se interpretan asi:

- **MSE (Error Cuadratico Medio):** promedio de los errores de ingreso al
	cuadrado. Penaliza especialmente los fallos monetarios grandes, aunque queda
	expresado en euros cuadrados y puede estar dominado por pocos meses extremos.
- **PSI (Population Stability Index):** compara la distribucion historica del
	ingreso de entrenamiento con la distribucion de los pronosticos futuros,
	usando deciles historicos. Un valor bajo indica estabilidad; como referencia
	operativa, menos de 0.10 suele ser estable, entre 0.10 y 0.25 requiere
	seguimiento y por encima de 0.25 sugiere un cambio relevante de poblacion.
- **Gini normalizado:** mide si el modelo ordena correctamente los meses desde
	menor hasta mayor ingreso. Un valor cercano a 1 indica buen ranking, 0 indica
	ausencia de capacidad de ordenacion y un valor negativo indica orden inverso.
- **K2 de D'Agostino-Pearson:** comprueba si los residuos presentan asimetria o
	colas incompatibles con una distribucion normal. Se reporta junto con su
	`p-value`; un valor inferior a 0.05 alerta de errores no normales y de un
	posible riesgo subestimado en escenarios extremos.

El MSE no basta por si solo: resume el tamano medio del error, pero no detecta
un cambio estructural entre periodos (PSI), si el modelo prioriza correctamente
los meses de mayor ingreso (Gini), ni si existen sesgos o colas extremas en los
errores (K2). Finanzas necesita las cuatro perspectivas para valorar precision,
estabilidad y riesgo de planificacion.

Resultado de referencia con el dataset actual y 500 arboles:

| Metrica | Resultado | Lectura para Finanzas |
| --- | ---: | --- |
| MSE | 10,003,116,724.14 EUR² | Existen errores monetarios relevantes al elevarlos al cuadrado. |
| PSI | 8.1017 | Hay un cambio muy fuerte respecto al historico de entrenamiento. |
| Gini normalizado | 0.9470 | El modelo ordena muy bien los meses por nivel de ingreso. |
| K2 | 12.7028 (`p-value` 0.0017) | Los residuos no parecen normales; las colas requieren cautela. |

Instalacion y ejecucion:

```bash
python -m pip install pandas scikit-learn scipy
PYTHONPATH=src python src/model_training.py
```

---

## Milestones (reference)

| Milestone | Focus        | Typical deliverables                        |
| --------- | ------------ | ------------------------------------------- |
| 0         | Prework      | Environment setup, first prompts            |
| 1         | Web          | Corporate website, forms, SEO               |
| 2         | Programming  | Business logic, scoring, calculations       |
| 3         | AI-driven UI | AI-generated interfaces                     |
| 4         | Next.js      | Portals, loyalty app, operations UI         |
| 5         | Backend      | Central API (locations, menus, sales, etc.) |
| 6         | Telemetry    | Data pipeline, dashboards                   |
| 7         | RAG & Memory | Semantic knowledge base, search             |
| 8         | Agents       | Support, onboarding, training agents        |
| 9         | Workflows    | n8n automations                             |
| 10        | Real-time    | Live dashboards, alerts, streaming          |

---

## Links

- [4Geeks Academy — AI Engineering](https://4geeksacademy.com/es/programas-de-carrera/ingenieria-ia)
- [How to start a coding project](https://4geeks.com/lesson/how-to-start-a-project)

---

## Contributors

This template was built as part of the 4Geeks Academy AI Engineering Career Program by [@marcogonzalo](https://www.linkedin.com/in/marcogonzalo) and [@alezanchezr](https://x.com/alesanchezr) and many other contributors. Find out more about our [AI Engineering Course](https://4geeksacademy.com/en/career-programs/ai-engineering), and [other courses](https://4geeksacademy.com/en/program-comparison).

You can find other templates and resources like this at the [4Geeks Academy GitHub page](https://github.com/4geeksacademy).

_This template is maintained by 4Geeks Academy for the AI Engineering track. For exclusive use in the programme._
