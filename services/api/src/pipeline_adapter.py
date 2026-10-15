"""Lazy adapter to the rfp_intake pipeline living in ``data/pipelines/src``.

Same pattern as ``src/agent/rag_adapter.py``: the FastAPI process never owns
the graph — it locates the pipelines package at runtime, imports it and calls
``run_pipeline()``. Routers/services only TRIGGER and QUERY the pipeline.
"""

from __future__ import annotations

import importlib
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any


@lru_cache(maxsize=1)
def _runner_module() -> ModuleType:
    for ancestor in Path(__file__).resolve().parents:
        pipeline_source = ancestor / "data" / "pipelines" / "src"
        if (pipeline_source / "rfp_intake" / "runner.py").is_file():
            pipeline_path = str(pipeline_source)
            if pipeline_path not in sys.path:
                sys.path.insert(0, pipeline_path)
            return importlib.import_module("rfp_intake.runner")

    raise RuntimeError(
        "No se encontro el modulo rfp_intake en data/pipelines/src/rfp_intake/runner.py"
    )


def run_pipeline(ticket_id: str, pdf_path: Path, artifacts_dir: Path | None = None) -> Any:
    """Execute the full intake pipeline for one ticket. Returns an IntakeResult."""
    return _runner_module().run_pipeline(ticket_id, pdf_path, artifacts_dir)


def status_descartado() -> str:
    return _runner_module().STATUS_DESCARTADO


def status_analisis_completo() -> str:
    return _runner_module().STATUS_ANALISIS_COMPLETO
