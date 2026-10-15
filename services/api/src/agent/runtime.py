from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from src.agent.graph import build_agent_graph
from src.agent.mcp_tools import AgentMCPTools
from src.agent.memory_store import PostgresAgentMemoryStore


def _checkpoint_connection_string() -> str:
    connection_string = os.getenv("SQL_URL", "").strip()
    if not connection_string:
        raise RuntimeError("La variable SQL_URL es obligatoria para el checkpoint del agente.")
    return (
        connection_string.replace("postgresql+psycopg2://", "postgresql://", 1)
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )


def _configure_langsmith() -> None:
    if os.getenv("LANGSMITH_API_KEY") and os.getenv("LANGSMITH_TRACING", "").lower() == "true":
        os.environ.setdefault("LANGSMITH_PROJECT", "trackflow-agent")


@asynccontextmanager
async def agent_graph_runtime() -> AsyncIterator[object]:
    _configure_langsmith()
    async with await AsyncConnection.connect(
        _checkpoint_connection_string(),
        autocommit=True,
        prepare_threshold=None,
        row_factory=dict_row,
    ) as connection:
        checkpointer = AsyncPostgresSaver(connection)
        await checkpointer.setup()
        memory_store = await PostgresAgentMemoryStore.connect()
        mcp_tools = AgentMCPTools()
        await mcp_tools.start()
        try:
            graph = build_agent_graph(
                checkpointer=checkpointer,
                incident_lookup_fn=mcp_tools.lookup_incidents,
                inventory_lookup_fn=mcp_tools.lookup_inventory,
            )
            graph.memory_store = memory_store
            yield graph
        finally:
            await mcp_tools.aclose()
            await memory_store.aclose()