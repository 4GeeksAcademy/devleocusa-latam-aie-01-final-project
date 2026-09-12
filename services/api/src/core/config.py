"""Centralized settings for TrackFlow services.

Reads configuration from environment variables with strict typing.
Kept intentionally minimal and free of database/model imports to
avoid circular dependencies when used by Celery workers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Immutable application settings loaded once at import time."""

    redis_url: str


def _get_env(name: str, *, default: str | None = None, required: bool = True) -> str:
    """Retrieve an environment variable with type safety.

    Parameters
    ----------
    name:
        Environment variable name.
    default:
        Fallback value when the variable is absent.
    required:
        When *True* and no default is provided, raise ``ValueError``
        if the variable is missing or empty.

    Raises
    ------
    ValueError
        If the variable is required but not set.
    """
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if default is not None:
        return default
    if required:
        raise ValueError(
            f"Required environment variable '{name}' is not set. "
            f"Add it to your .env file or export it in your shell."
        )
    return ""


def load_settings() -> Settings:
    """Build a ``Settings`` instance from environment variables."""
    return Settings(
        redis_url=_get_env("REDIS_URL", default="redis://localhost:6379/0"),
    )


# Module-level singleton — imported once, immutable thereafter.
settings = load_settings()
