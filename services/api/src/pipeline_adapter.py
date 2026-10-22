"""Lazy adapter to the rfp_intake pipeline living in ``data/pipelines/src``.

Same pattern as ``src/agent/rag_adapter.py``: the FastAPI process never owns
the graph — it locates the pipelines package at runtime, imports it and calls
``run_pipeline()``. Routers/services only TRIGGER and QUERY the pipeline.
"""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
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


def run_pipeline(
    ticket_id: str,
    pdf_path: Path,
    artifacts_dir: Path | None = None,
    *,
    on_classified: Any = None,
) -> Any:
    """Execute the intake pipeline for one ticket and optionally observe classification."""
    return _runner_module().run_pipeline(
        ticket_id, pdf_path, artifacts_dir, on_classified=on_classified
    )


def status_descartado() -> str:
    return _runner_module().STATUS_DESCARTADO


def status_analisis_completo() -> str:
    return _runner_module().STATUS_ANALISIS_COMPLETO


def run_proposal_handoff(handoff: dict[str, Any], *, max_iterations: int, on_update: Any, generator: Any = None) -> dict[str, Any]:
    """Run Parte 2 against the already-persisted Part 1 synthesizer payload."""
    pipeline_source = next(
        (ancestor / "data" / "pipelines" / "src" for ancestor in Path(__file__).resolve().parents
         if (ancestor / "data" / "pipelines" / "src" / "rfp_intake" / "proposal.py").is_file()),
        None,
    )
    if pipeline_source is None:
        raise RuntimeError("No se encontró data/pipelines/src/rfp_intake/proposal.py")
    if str(pipeline_source) not in sys.path:
        sys.path.insert(0, str(pipeline_source))
    import asyncio
    module = importlib.import_module("rfp_intake.proposal")
    return asyncio.run(module.run_proposal_handoff(
        handoff, max_iterations=max_iterations, on_update=on_update, generator=generator
    ))


def _approval_module() -> ModuleType:
    pipeline_source = next(
        (ancestor / "data" / "pipelines" / "src" for ancestor in Path(__file__).resolve().parents
         if (ancestor / "data" / "pipelines" / "src" / "rfp_intake" / "approval.py").is_file()),
        None,
    )
    if pipeline_source is None:
        raise RuntimeError("No se encontró el grafo rfp_intake.approval")
    if str(pipeline_source) not in sys.path:
        sys.path.insert(0, str(pipeline_source))
    return importlib.import_module("rfp_intake.approval")


def invoke_department_approval(graph: Any, **kwargs: Any) -> dict[str, Any]:
    """Start/resume an isolated department thread using the approval graph."""
    _approval_module()
    from rfp_intake.approval import invoke_department_approval as invoke
    return invoke(graph, **kwargs)


def build_department_approval_graph(**kwargs: Any) -> Any:
    return _approval_module().build_department_approval_graph(**kwargs)


def arbitrate_conflicts(sections: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    return _approval_module().arbitrate_conflicts(sections, **kwargs)


def build_async_department_approval_graph(**kwargs: Any) -> Any:
    """Deprecated: RFP approval currently uses the isolated sync PostgresSaver."""
    raise RuntimeError("Use department_approval_runtime() for the RFP approval graph.")


@contextmanager
def department_approval_runtime(*, on_trace: Any = None):
    """Open the dedicated RFP PostgreSQL saver; never shares the CX graph/checkpointer."""
    from langgraph.checkpoint.postgres import PostgresSaver
    import psycopg

    connection_string = os.getenv("SQL_URL", "").strip()
    if not connection_string:
        raise RuntimeError("SQL_URL es obligatoria para checkpoint RFP.")
    connection_string = (
        connection_string.replace("postgresql+psycopg2://", "postgresql://", 1)
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )
    with psycopg.connect(connection_string, autocommit=True, prepare_threshold=None) as connection:
        saver = PostgresSaver(connection)
        saver.setup()
        module = _approval_module()
        generator, evaluator = proposal_helpers()
        graph = module.build_department_approval_graph(
            checkpointer=saver,
            generator=generator,
            evaluator=evaluator,
            on_trace=on_trace,
        )
        yield graph


async def invoke_department_approval_async(graph: Any, **kwargs: Any) -> dict[str, Any]:
    """Async counterpart used by FastAPI; preserves LangGraph async checkpoints."""
    _approval_module()
    from rfp_intake.approval import department_thread_id, validate_decision
    from langgraph.types import Command

    config = {"configurable": {"thread_id": department_thread_id(kwargs["ticket_id"], kwargs["department_id"])}}
    resume = kwargs.pop("resume", None)
    if resume is not None:
        result = await graph.ainvoke(Command(resume=validate_decision(resume)), config=config)
    else:
        result = await graph.ainvoke({key: kwargs[key] for key in (
            "ticket_id", "department_id", "workstream", "summary", "max_iterations"
        )} | {"iteration_count": 0}, config=config)
    return result


def proposal_helpers() -> tuple[Any, Any]:
    """Return lazy-loaded Hito 9 generator/evaluator from the existing pipeline."""
    pipeline_source = next(
        (ancestor / "data" / "pipelines" / "src" for ancestor in Path(__file__).resolve().parents
         if (ancestor / "data" / "pipelines" / "src" / "rfp_intake" / "proposal.py").is_file()),
        None,
    )
    if pipeline_source is None:
        raise RuntimeError("No se encontró data/pipelines/src/rfp_intake/proposal.py")
    if str(pipeline_source) not in sys.path:
        sys.path.insert(0, str(pipeline_source))
    module = importlib.import_module("rfp_intake.proposal")
    return module.generate_hito9_section, module.evaluate_hito9_section
