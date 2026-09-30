# Documento de Diseño RAG — TrackFlow

> Este documento describe la arquitectura, decisiones técnicas y flujo de extremo a extremo del sistema RAG (Retrieval-Augmented Generation) implementado para TrackFlow.

---

## 1. Flujo RAG de extremo a extremo

```
┌─────────────────────┐    ┌──────────────────┐    ┌────────────────┐
│  docs/company-      │    │  data/process/   │    │    Qdrant      │
│  knowledge-base/    │───▶│  rag.py          │───▶│  (vector DB)   │
│  (4 docs .md)       │    │  setup() + embed │    │  4 vectors     │
└─────────────────────┘    └──────────────────┘    └───────┬────────┘
                                                          │
                                                          │  retrieve()
                                                          ▼
┌─────────────────────┐    ┌──────────────────┐    ┌────────────────┐
│  Usuario (UI)       │───▶│  POST /knowledge │───▶│  data/pipeline │
│  Pregunta en NL     │◀───│  /query          │◀───│  s/rag.py      │
└─────────────────────┘    └──────────────────┘    │  query()       │
                                                   │  = retrieve()  │
                                                   │  + generate()  │
                                                   └────────────────┘
```

### Pasos detallados

1. **Indexación (offline, `setup()`):**
   - Lee los 4 documentos Markdown de `docs/company-knowledge-base/`.
   - Cada documento se parsea y se divide en chunks semánticos.
   - Cada chunk se convierte a vector con `embed()` (modelo `text-embedding-3-small`).
   - Se insertan en la colección `trackflow-knowledge-base` de Qdrant con payload completo.

2. **Consulta (online, `query()`):**
   - La UI envía `POST /knowledge/query` con `{ "question": "..." }`.
   - `retrieve()` embebe la pregunta y busca los 5 vecinos más cercanos en Qdrant.
   - Se filtran resultados por debajo de `min_score = 0.3`.
   - `generate_answer()` construye un prompt con los chunks recuperados y la pregunta.
   - El LLM de generación (`gpt-4o-mini`) genera la respuesta final.
   - Se devuelve `{ "answer": "..." }` al cliente.

---

## 2. Estrategia de Chunking

### Algoritmo

El chunking se implementa en `_chunk_markdown()` dentro de `data/process/rag.py`:

1. **División por encabezados Markdown** (`#`, `##`, `###`): se busca preservar unidades semánticas coherentes (políticas, procedimientos, categorías).
2. **División por párrafos** (`\n\n`): si una sección excede el umbral de tokens (~400 tokens), se subdivide por párrafos dobles.
3. **Preservación de integridad**: nunca se corta una frase o regla por la mitad.

### Resultado actual

| Documento | Chunks | Tokens estimados |
|-----------|--------|-----------------|
| `trackflow-carrier-coverage.es.md` | 1 | ~252 |
| `trackflow-returns-policy.es.md` | 1 | ~303 |
| `trackflow-sla-delivery.es.md` | 1 | ~275 |
| `trackflow-storage-pricing.es.md` | 1 | ~251 |
| **Total** | **4** | **~1,081** |

Los documentos actuales son cortos (~250-300 tokens cada uno), por lo que cada documento completo cabe en un solo chunk dentro del límite de 400 tokens. Esto es adecuado para el corpus actual: cada chunk es una unidad semántica completa que contiene toda la información de una política o procedimiento.

### Por qué esta estrategia

- **Documentos pequeños**: con ~250 tokens por documento, no hay riesgo de pérdida de contexto.
- **Preservación de reglas**: al mantener documentos enteros como chunks, las condiciones, excepciones y valores numéricos nunca se separan de su contexto.
- **Escalabilidad**: cuando se añadan documentos más largos, la lógica de subdivisión por párrafos entrará en acción automáticamente.

---

## 3. Prácticas de Embeddings

### Modelos utilizados

| Función | Modelo | Rol |
|---------|--------|-----|
| `embed()` | `text-embedding-3-small` | Generar vectores para chunks y consultas |
| `generate_answer()` | `gpt-4o-mini` | Generar la respuesta en lenguaje natural |

> **Importante:** se usan IDs de modelo **distintos** para embeddings y generación. Nunca se reutiliza el modelo de generación para embeddings.

### Consistencia

La misma función `embed()` se utiliza tanto en `data/process/rag.py` (indexación) como en `data/pipelines/rag.py` (consulta). Esto garantiza que los vectores de chunks y consultas están en el mismo espacio semántico.

### Parámetros técnicos

| Parámetro | Valor |
|-----------|-------|
| Modelo de embeddings | `text-embedding-3-small` (OpenAI) |
| Dimensión del vector | 1536 |
| Métrica de distancia en Qdrant | Cosine |
| `min_score` (umbral de relevancia) | 0.3 |
| `k` (número de resultados por consulta) | 5 |
| Batch size de inserción | 50 puntos por llamada |

### Normalización

- No se aplica normalización adicional al texto antes de embeber: el modelo `text-embedding-3-small` maneja internamente la tokenización y normalización.
- Se preserva el formato Markdown original en el payload para que el LLM de generación pueda interpretar estructura (listas, negritas, etc.).

---

## 4. Idempotencia de Indexación

**Estrategia: CLEAN AND RELOAD** — en cada ejecución de `setup()` se elimina la colección completa y se recrea desde cero.

### Justificación

- **Simplicidad**: no requiere lógica de detección de duplicados ni actualización parcial.
- **Determinismo**: los IDs de puntos se generan con SHA-256 de `{source_document}::{chunk_index}`, lo que garantiza que el mismo contenido siempre obtiene el mismo ID.
- **Desarrollo**: re-ejecutar `setup()` siempre produce el mismo resultado, facilitando debugging y pruebas.

### Trade-off

En producción con documentos que cambian frecuentemente, esta estrategia implica re-indexar todo el corpus. Para el volumen actual (4 documentos, ~4 chunks) el costo es despreciable. Si el corpus crece significativamente, se podría migrar a una estrategia de upsert por ID con detección de cambios.

---

## 5. Estructura de Archivos

```
data/
├── process/
│   └── rag.py              ← setup() + embed() + chunking
├── pipelines/
│   └── src/pipelines/
│       └── rag.py          ← retrieve() + generate_answer() + query()
└── eval/
    ├── test-queries.json   ← 10 preguntas de evaluación
    ├── recall_at_3.py      ← Script de evaluación Recall@3
    └── recall_at_3_report.json

services/
└── api/src/routes/
    └── knowledge_router.py ← POST /knowledge/query

uis/
└── backoffice/app/knowledge/
    └── page.tsx            ← UI de consulta

docs/
├── company-knowledge-base/ ← Corpus fuente (4 documentos .md)
└── rag/
    └── rag-design.md       ← Este documento
```

---

## 6. Payload de Qdrant

Cada punto en la colección `trackflow-knowledge-base` contiene:

```json
{
  "text": "Contenido completo del chunk...",
  "section": "Nombre de la sección Markdown",
  "source_document": "trackflow-returns-policy.es.md",
  "company": "TrackFlow",
  "language": "es",
  "chunk_index": 0
}
```

Campos del payload:
- **`text`**: cuerpo del chunk para incluir en el prompt de generación.
- **`source_document`**: nombre del archivo fuente (para citar la fuente).
- **`section`**: encabezado de la sección (para contexto adicional).
- **`company`**: siempre `"TrackFlow"`.
- **`language`**: `"es"` o `"en"` (detectado por extensión del archivo).
- **`chunk_index`**: índice secuencial dentro del documento.

---

## 7. Evaluación

### Recall@3

| Métrica | Valor |
|---------|-------|
| Total de preguntas | 10 |
| Hits (chunk correcto en top-3) | 10 |
| **Recall@3** | **100%** |
| Umbral mínimo requerido | 80% |

Las 10 preguntas cubren los 4 documentos fuente:
- 3 preguntas sobre política de devoluciones
- 2 preguntas sobre cobertura de transportistas
- 2 preguntas sobre SLA de entrega
- 3 preguntas sobre tarifas de almacenamiento

### Ejecutar evaluación

```bash
# Modo offline (sin Qdrant, usa keyword matching)
cd data/pipelines && uv run python ../eval/recall_at_3.py

# Modo live (requiere Qdrant corriendo con datos indexados)
cd data/pipelines && uv run python ../eval/recall_at_3.py --live
```

---

## 8. Variables de Entorno

```env
# Qdrant
QDRANT_URL=http://qdrant:6333

# Embeddings (modelo dedicado para vectores)
EMBEDDINGS_MODEL_ID=text-embedding-3-small
EMBEDDINGS_API_KEY=<tu-api-key>
EMBEDDINGS_BASE_URL=https://api.openai.com/v1

# Generación (modelo distinto para respuestas)
GENERATION_MODEL_ID=gpt-4o-mini
GENERATION_API_KEY=<tu-api-key>
GENERATION_BASE_URL=https://api.openai.com/v1
```

---

*Documento generado para el proyecto TrackFlow — AI Engineering · 4Geeks Academy*
