from __future__ import annotations

from typing import Any

from src.agent.trace_store import record_agent_trace


async def invoke_agent(
    graph: Any,
    question: str,
    run_id: str,
) -> dict[str, Any]:
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
                events.append({"node": node_name, "output": _trace_output(node_name, output)})
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


def _trace_output(node_name: str, output: dict[str, Any]) -> dict[str, Any]:
    if node_name == "classify":
        return {
            "sources": output.get("sources", []),
            "route_failed": bool(output.get("route_error")),
        }
    if node_name == "retrieve":
        return {"context_items": len(output.get("context", []))}
    if node_name == "incident_tool":
        result = output.get("incident_result", {})
        return {
            "status": result.get("status"),
            "record_count": len(result.get("incidents", [])),
        }
    if node_name == "inventory_tool":
        result = output.get("inventory_result", {})
        return {
            "status": result.get("status"),
            "record_count": len(result.get("products", [])),
        }
    return output