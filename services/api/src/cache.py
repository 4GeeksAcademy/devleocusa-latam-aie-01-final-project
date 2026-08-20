"""Simple in-memory TTL cache backed by a dictionary.

No external dependencies required.  Thread-safe for typical single-process
ASGI workers (uvicorn with one worker per process).

Usage::

    from src.cache import TTLCache

    summary_cache = TTLCache(ttl_seconds=30)

    # Check before expensive computation
    cached = summary_cache.get("my-key")
    if cached is not None:
        return cached

    # Compute and store
    result = expensive_computation()
    summary_cache.set("my-key", result)
    return result

    # Invalidate on writes
    summary_cache.invalidate("my-key")
"""

from __future__ import annotations

import time
from typing import Any


class TTLCache:
    """In-memory cache where each entry expires after *ttl_seconds*.

    Uses ``time.monotonic()`` internally so it is immune to system clock
    adjustments.

    Parameters
    ----------
    ttl_seconds : int
        Time-to-live in seconds for each cached entry (default 30).
    """

    __slots__ = ("_ttl", "_store")

    def __init__(self, ttl_seconds: int = 30) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        """Return cached *value* for *key*, or ``None`` if missing/expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            # Lazy expiration
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        """Store *value* under *key* with the configured TTL."""
        self._store[key] = (time.monotonic() + self._ttl, value)

    def invalidate(self, key: str) -> None:
        """Remove *key* from the cache (no-op if missing)."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove **all** entries from the cache."""
        self._store.clear()

    @property
    def size(self) -> int:
        """Return the number of entries currently in the cache."""
        return len(self._store)


# ── Shared cache instances ──────────────────────────────────────────────
# These are imported by multiple routers for cross-module invalidation.
# Cache keys are always scoped to the authenticated user when the data
# is user-specific, preventing accidental data leaks between users.

# Cache for GET /auth/me — keyed by user_id (str(current_user.id)).
# Invalidated by profiles_router when the profile is updated, and by
# auth_router when the password changes.
me_cache = TTLCache(ttl_seconds=30)

# Cache for GET /profiles/me — keyed by user_id (str(current_user.id)).
# Separate from me_cache to avoid type collisions (MeResponse vs ProfileResponse).
# Invalidated by PUT /profiles/me and PUT /users/{id}.
profile_cache = TTLCache(ttl_seconds=30)

# Cache for GET /suppliers and GET /suppliers/{supplier_id}.
# Suppliers data changes very rarely (days/weeks), so a long TTL is safe.
# Key: serialized filter string for the list, supplier_id for detail.
suppliers_list_cache = TTLCache(ttl_seconds=300)   # 5 min
supplier_cache = TTLCache(ttl_seconds=300)          # 5 min

# Cache for GET /inventory/products and GET /inventory/products/{sku_id}.
# Product metadata changes rarely; stock changes with entries/exits.
inventory_products_cache = TTLCache(ttl_seconds=30)
inventory_product_cache = TTLCache(ttl_seconds=30)

# Cache for GET /users (admin listing). User data changes rarely.
users_list_cache = TTLCache(ttl_seconds=120)  # 2 min