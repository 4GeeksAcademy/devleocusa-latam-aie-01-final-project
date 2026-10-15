"""Agents of the rfp_intake graph: classifier, orchestrator, worker, synthesizer.

Each agent is a thin, testable function: plain input → typed output. None of
them touches the database — persistence belongs to runner.py.
"""

from __future__ import annotations

__all__ = [
    "classifier",
    "orchestrator",
    "worker",
    "synthesizer",
]
