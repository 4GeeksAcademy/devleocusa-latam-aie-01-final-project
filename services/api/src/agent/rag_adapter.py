from __future__ import annotations

import importlib
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any


@lru_cache(maxsize=1)
def _rag_module() -> ModuleType:
    for ancestor in Path(__file__).resolve().parents:
        pipeline_source = ancestor / "data" / "pipelines" / "src"
        if (pipeline_source / "pipelines" / "rag.py").is_file():
            pipeline_path = str(pipeline_source)
            if pipeline_path not in sys.path:
                sys.path.insert(0, pipeline_path)
            return importlib.import_module("pipelines.rag")

    raise RuntimeError("No se encontró el módulo RAG data/pipelines/src/pipelines/rag.py")


def retrieve(question: str) -> list[dict[str, Any]]:
    return _rag_module().retrieve(question)


def generate_answer(question: str, context: list[dict[str, Any]]) -> str:
    return _rag_module().generate_answer(question, context)


def no_context_message() -> str:
    return _rag_module().NO_CONTEXT_MESSAGE