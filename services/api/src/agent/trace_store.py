from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _trace_path() -> Path:
    configured_path = os.getenv("AGENT_TRACE_PATH")
    if configured_path:
        return Path(configured_path).expanduser()
    return Path(__file__).resolve().parents[2] / "data" / "agent_traces.jsonl"


def record_agent_trace(
    *,
    run_id: str,
    question: str,
    events: list[dict[str, Any]],
    answer: str | None,
    error_type: str | None = None,
) -> None:
    trace_path = _trace_path()
    trace_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    trace = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "question": question,
        "events": events,
        "answer": answer,
        "error_type": error_type,
    }
    payload = (json.dumps(trace, ensure_ascii=False, default=str) + "\n").encode("utf-8")
    descriptor = os.open(trace_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)