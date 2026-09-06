"""Pytest configuration for the pipeline test suite.

Ensures that ``data/pipelines/`` is in ``sys.path`` so that
``from pipeline import ...`` works regardless of working directory.

Also monkey-patches ``prefect.logging.get_run_logger`` so that
task functions can be tested without a full Prefect orchestration
context (the test harness provides enough context for task execution,
but ``get_run_logger`` may still fail in some edge cases).
"""

import logging
import sys
from pathlib import Path

import pytest

# ────────────────────────────────────────────────────────────────────
# Path setup
# ────────────────────────────────────────────────────────────────────

_THIS_DIR = Path(__file__).resolve().parent  # tests/pipelines/
_PROJECT_ROOT = _THIS_DIR.parent.parent  # repo root
_PIPELINE_DIR = _PROJECT_ROOT / "data" / "pipelines"

if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

# ────────────────────────────────────────────────────────────────────
# Global Prefect mock  —  get_run_logger safety net
# ────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_prefect_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``prefect.logging.get_run_logger`` with a plain logger.

    This ensures that tasks using ``get_run_logger()`` do not raise
    ``MissingContextError`` when called from tests via the Prefect test
    harness.
    """
    monkeypatch.setattr(
        "prefect.logging.get_run_logger",
        lambda: logging.getLogger("trackflow.test"),
    )