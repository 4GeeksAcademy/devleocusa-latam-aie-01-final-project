"""RFP intake pipeline (Parte 1) — dedicated LangGraph graph for TrackFlow.

This package is intentionally separate from the CX / knowledge-agent graph
(`data/pipelines/pipeline.py` / `pipelines.rag`). It implements:

    conversion.py  PDF → Markdown (MarkItDown) + readability metrics prep
    metadata.py    document metadata + py-readability-metrics scoring
    state.py       shared LangGraph state for the rfp_intake graph
    agents/        classifier / orchestrator / worker / synthesizer
    graph.py       the composed rfp_intake graph
    runner.py      end-to-end execution + Supabase persistence

Routers under services/ only trigger and query this pipeline; they never own it.
"""

from __future__ import annotations

__all__ = [
    "conversion",
    "metadata",
]
