from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

API_SOURCE = str(Path(__file__).resolve().parents[2] / "services" / "api")
API_PACKAGE = str(Path(API_SOURCE) / "src")
if API_SOURCE not in sys.path:
    sys.path.insert(0, API_SOURCE)

_original_cwd = Path.cwd()
os.chdir(API_SOURCE)
import src
os.chdir(_original_cwd)

if API_PACKAGE not in src.__path__:
    src.__path__.append(API_PACKAGE)

from src.agent.routing import classify_question
from src.env_loader import load_env_if_available

load_env_if_available()


LIVE_EVALS_ENABLED = (
    os.getenv("RUN_LIVE_AGENT_EVALS") == "1"
    and bool(os.getenv("GENERATION_API_KEY") or os.getenv("OPENAI_API_KEY"))
)

pytestmark = pytest.mark.skipif(
    not LIVE_EVALS_ENABLED,
    reason="Set RUN_LIVE_AGENT_EVALS=1 and configure the generation API key to run live LLM routing evals.",
)


@pytest.mark.parametrize(
    ("question", "expected_source"),
    [
        ("¿En qué estado está el ticket 482?", "incidents"),
        ("¿Cuál es la política de devoluciones de TrackFlow?", "rag"),
    ],
)
def test_live_classifier_routes_to_the_required_source_only(
    question: str,
    expected_source: str,
) -> None:
    decision = classify_question(question)

    assert decision.sources == [expected_source]
    if expected_source == "incidents":
        assert decision.incident is not None
        assert decision.incident.ticket_id == "482"
    else:
        assert decision.incident is None
        assert decision.inventory is None