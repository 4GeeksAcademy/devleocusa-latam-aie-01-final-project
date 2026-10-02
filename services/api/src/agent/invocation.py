from __future__ import annotations

from typing import Any

from src.agent.trace_store import record_agent_trace


async def invoke_agent(graph: Any, question: str, run_id: str) -> dict[str, Any]:
    config = {
        "configurable": {"thread_id": run_id},
        "metadata": {"run_id": run_id},
        "run_name": "trackflow-knowledge-agent",
    }
    events: list[dict[str, Any]] = []
    final_state: dict[str, Any] = {}

    try:
        async for update in graph.astream(
            {"question": question},
            config=config,
            stream_mode="updates",
        ):
            for node_name, output in update.items():
                events.append({"node": node_name, "output": output})
                final_state.update(output)
    except Exception as error:
        record_agent_trace(
            run_id=run_id,
            question=question,
            events=events,
            answer=None,
            error_type=type(error).__name__,
        )
        raise

    answer = final_state.get("answer")
    record_agent_trace(
        run_id=run_id,
        question=question,
        events=events,
        answer=answer,
    )
    return final_state