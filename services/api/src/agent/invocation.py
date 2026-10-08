from __future__ import annotations

from typing import Any

from src.agent.trace_store import record_agent_trace
from src.agent.memory_generation import classify_pending_decision
from src.agent.memory_models import MemoryDecisionResult


async def invoke_agent(
    graph: Any,
    question: str,
    run_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    memory_store = getattr(graph, "memory_store", None)
    effective_question = question
    loaded_memories = []
    if user_id and memory_store is not None:
        loaded_memories = await memory_store.memories(user_id)
        pending = await memory_store.pending(user_id)
        if pending:
            try:
                decision = MemoryDecisionResult.model_validate(
                    classify_pending_decision(pending.content, question)
                )
            except Exception:
                decision = MemoryDecisionResult(decision="reject")
            if decision.decision.value == "approve" and decision.explicit_confirmation:
                resolved = await memory_store.resolve(
                    pending,
                    decision="approve",
                    decision_message=question,
                    explicit_confirmation=decision.explicit_confirmation,
                )
                if not resolved:
                    return {"answer": "No se pudo confirmar la decisión; no se guardó la memoria."}
                effective_question = decision.continuation
                if not effective_question:
                    return {"answer": "De acuerdo, recordaré esto para próximas interacciones."}
            elif decision.decision.value == "reject":
                resolved = await memory_store.resolve(
                    pending, decision="reject", decision_message=question
                )
                if not resolved:
                    return {"answer": "No se pudo registrar la decisión; no se modificó la memoria."}
                effective_question = decision.continuation
                if not effective_question:
                    return {"answer": "Entendido, no guardaré esa información."}
            elif decision.decision.value == "edit":
                resolved = await memory_store.resolve(
                    pending,
                    decision="edit",
                    decision_message=question,
                    edited_content=decision.edited_content,
                )
                if not resolved:
                    return {"answer": "No se pudo registrar la edición; no se modificó la memoria."}
                if decision.edited_content:
                    try:
                        await memory_store.propose(
                            user_id,
                            decision.edited_content,
                            "Edición solicitada por el usuario; requiere aprobación explícita.",
                            question,
                            category=pending.category,
                            memory_key=pending.memory_key,
                            repetition_count=pending.repetition_count,
                        )
                    except ValueError:
                        # The edit is untrusted; never show it as pending if validation/storage failed.
                        pass
                effective_question = decision.continuation
                if not effective_question:
                    if decision.edited_content and await memory_store.pending(user_id):
                        return {"answer": "Preparé una nueva propuesta; ¿quieres que recuerde esa versión?"}
                    return {"answer": "No pude aceptar esa edición como propuesta válida; no se guardó."}
            else:
                resolved = await memory_store.resolve(
                    pending,
                    decision=("reject" if decision.decision.value in {"approve", "uncertain"}
                              else decision.decision.value),
                    decision_message=question,
                )
                if not resolved:
                    return {"answer": "No se pudo registrar la respuesta; no se modificó la memoria."}

    if not effective_question.strip():
        return {"answer": "No recibí una pregunta nueva para continuar."}
    config = {
        "configurable": {"thread_id": run_id},
        "metadata": {"run_id": run_id},
        "run_name": "trackflow-knowledge-agent",
    }
    events: list[dict[str, Any]] = []
    final_state: dict[str, Any] = {}

    try:
        async for update in graph.astream(
            {
                "question": effective_question,
                "user_id": user_id or "",
                "memories": [item.content for item in loaded_memories],
            },
            config=config,
            stream_mode="updates",
        ):
            for node_name, output in update.items():
                events.append({"node": node_name, "output": _trace_output(node_name, output)})
                final_state.update(output)
    except Exception as error:
        record_agent_trace(
            run_id=run_id,
            question=effective_question,
            events=events,
            answer=None,
            error_type=type(error).__name__,
        )
        raise

    answer = final_state.get("answer")
    record_agent_trace(
        run_id=run_id,
        question=effective_question,
        events=events,
        answer=answer,
    )
    proposal = final_state.get("memory_proposal")
    if user_id and memory_store is not None and proposal:
        try:
            if not await memory_store.pending(user_id):
                await memory_store.propose(
                    user_id,
                    proposal["content"],
                    proposal["reason"],
                    effective_question,
                    category=proposal["category"],
                    memory_key=proposal["memory_key"],
                    country=proposal.get("country"),
                    repetition_count=proposal.get("repetition_count"),
                )
        except Exception:
            # The model proposal is optional; do not report it as pending on failure.
            final_state["answer"] = final_state["answer"].split("\n\n¿Quieres que recuerde", 1)[0]
            final_state["memory_proposal"] = None
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