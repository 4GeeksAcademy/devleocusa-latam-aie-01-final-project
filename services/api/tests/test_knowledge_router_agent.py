from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.agent.graph import build_agent_graph
from src.routes.knowledge_router import KnowledgeQueryRequest, knowledge_query, knowledge_router
from src.agent.state import RoutingDecision


def _request_for(graph):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent_graph=graph)))


def _rag_route(_question: str) -> RoutingDecision:
    return RoutingDecision(sources=["rag"])


def _client_for(graph) -> TestClient:
    app = FastAPI()
    app.state.agent_graph = graph
    app.include_router(knowledge_router)
    return TestClient(app)


def test_knowledge_endpoint_invokes_graph_and_returns_trace_id(
    monkeypatch, tmp_path, test_user, auth_token
) -> None:
    monkeypatch.setenv("AGENT_TRACE_PATH", str(tmp_path / "traces.jsonl"))
    graph = build_agent_graph(
        classify_fn=_rag_route,
        retrieve_fn=lambda _question: [{"text": "Ventana: 30 días."}],
        generate_fn=lambda _question, context: context[0]["text"],
    )

    response = asyncio.run(
        knowledge_query(
            KnowledgeQueryRequest(question="¿Cuál es la ventana?"),
            _request_for(graph),
            _current_user=test_user[0],
        )
    )

    assert response.answer == "Ventana: 30 días."
    assert response.run_id

    http_response = _client_for(graph).post(
        "/knowledge/query",
        json={"question": "¿Cuál es la ventana?"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert http_response.status_code == 200
    assert http_response.json()["answer"] == response.answer
    assert http_response.json()["run_id"]


def test_knowledge_endpoint_hides_node_exception(
    monkeypatch, tmp_path, test_user, auth_token
) -> None:
    monkeypatch.setenv("AGENT_TRACE_PATH", str(tmp_path / "traces.jsonl"))

    def fail_retrieval(_question):
        raise RuntimeError("private backend detail")

    graph = build_agent_graph(classify_fn=_rag_route, retrieve_fn=fail_retrieval)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            knowledge_query(
                KnowledgeQueryRequest(question="¿Cuál es la ventana?"),
                _request_for(graph),
                _current_user=test_user[0],
            )
        )

    assert error.value.status_code == 500
    assert "private backend detail" not in str(error.value.detail)

    http_response = _client_for(graph).post(
        "/knowledge/query",
        json={"question": "¿Cuál es la ventana?"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert http_response.status_code == 500
    assert "private backend detail" not in http_response.text


def test_knowledge_endpoint_does_not_expose_graph_error(monkeypatch, auth_token) -> None:
    async def agent_with_internal_error(_graph, _question, _run_id):
        return {"error": "SQL_URL=private-database-credentials", "answer": ""}

    monkeypatch.setattr(
        "src.routes.knowledge_router.invoke_agent", agent_with_internal_error
    )
    http_response = _client_for(object()).post(
        "/knowledge/query",
        json={"question": "¿Cuál es la ventana?"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    assert http_response.status_code == 422
    assert http_response.json()["detail"] == "La pregunta no es válida."
    assert "private-database-credentials" not in http_response.text


def test_knowledge_endpoint_rejects_invalid_http_question(auth_token) -> None:
    http_response = _client_for(object()).post(
        "/knowledge/query",
        json={"question": ""},
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    assert http_response.status_code == 422


def test_knowledge_endpoint_rejects_requests_without_bearer_token() -> None:
    response = _client_for(object()).post(
        "/knowledge/query", json={"question": "¿Cuál es la ventana?"}
    )

    assert response.status_code == 401