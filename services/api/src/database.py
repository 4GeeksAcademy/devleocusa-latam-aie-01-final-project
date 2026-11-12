"""Database layer: TinyDB (local auth) + SQLModel (Supabase PostgreSQL).

TinyDB is kept for lightweight local authentication data.
The SQLModel engine connects to Supabase PostgreSQL for the inventory system.
"""

from __future__ import annotations

import json
import logging
import os
from threading import RLock
from collections.abc import Generator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from tinydb.table import Table

# ── Local paths ──────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "suppliers.json"
DB_PATH = Path(os.getenv("TINYDB_PATH", str(DEFAULT_DB_PATH)))

# Ensure the destination directory exists before TinyDB opens the file.
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────
# TinyDB – used for authentication and simple local persistence
# ─────────────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)
_tinydb_lock = RLock()


class LockedTable(Table):
    """Make each read-modify-write table operation atomic in this process."""

    def insert(self, *args, **kwargs):
        with _tinydb_lock:
            return super().insert(*args, **kwargs)

    def insert_multiple(self, *args, **kwargs):
        with _tinydb_lock:
            return super().insert_multiple(*args, **kwargs)

    def update(self, *args, **kwargs):
        with _tinydb_lock:
            return super().update(*args, **kwargs)

    def update_multiple(self, *args, **kwargs):
        with _tinydb_lock:
            return super().update_multiple(*args, **kwargs)

    def upsert(self, *args, **kwargs):
        with _tinydb_lock:
            return super().upsert(*args, **kwargs)

    def remove(self, *args, **kwargs):
        with _tinydb_lock:
            return super().remove(*args, **kwargs)

    def truncate(self, *args, **kwargs):
        with _tinydb_lock:
            return super().truncate(*args, **kwargs)

    def get(self, *args, **kwargs):
        with _tinydb_lock:
            return super().get(*args, **kwargs)

    def all(self, *args, **kwargs):
        with _tinydb_lock:
            return super().all(*args, **kwargs)

    def search(self, *args, **kwargs):
        with _tinydb_lock:
            return super().search(*args, **kwargs)

    def contains(self, *args, **kwargs):
        with _tinydb_lock:
            return super().contains(*args, **kwargs)

    def count(self, *args, **kwargs):
        with _tinydb_lock:
            return super().count(*args, **kwargs)


class ThreadSafeJSONStorage(JSONStorage):
    """Serialize TinyDB file access across FastAPI worker threads.

    TinyDB's JSON storage truncates the database file before writing its next
    snapshot. Without a lock, another request can read during that brief
    interval and fail with ``JSONDecodeError`` (or observe partial JSON).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._io_lock = _tinydb_lock

    def read(self):
        with self._io_lock:
            try:
                return super().read()
            except json.JSONDecodeError:
                # A genuinely empty file is a valid empty TinyDB database.
                # This also recovers a file left empty by an interrupted write.
                if self._handle is not None:
                    self._handle.seek(0)
                    if not self._handle.read().strip():
                        logger.warning(
                            "TinyDB file %s was empty; initializing it as a new database",
                            self._handle.name,
                        )
                        return None
                raise

    def write(self, data):
        with self._io_lock:
            return super().write(data)

    def close(self):
        with self._io_lock:
            return super().close()


db = TinyDB(DB_PATH, storage=ThreadSafeJSONStorage)
db.table_class = LockedTable
suppliers_table = db.table("suppliers")
users_table = db.table("users")
profiles_table = db.table("profiles")
incidents_table = db.table("incidents")
leads_table = db.table("leads")
products_table = db.table("products")
stock_movements_table = db.table("stock_movements")
stock_reservations_table = db.table("stock_reservations")
carriers_table = db.table("carriers")
carrier_assignments_table = db.table("carrier_assignments")
chat_sessions_table = db.table("chat_sessions")
chat_messages_table = db.table("chat_messages")


def get_db() -> TinyDB:
    """Return the TinyDB client instance."""
    return db


def get_suppliers_table() -> Table:
    """Return the suppliers table handle."""
    return suppliers_table


def get_users_table() -> Table:
    """Return the users table handle."""
    return users_table


def get_profiles_table() -> Table:
    """Return the profiles table handle."""
    return profiles_table


def get_incidents_table() -> Table:
    """Return the incidents table handle."""
    return incidents_table


def get_leads_table() -> Table:
    """Return the lead intake and CRM table handle."""
    return leads_table


def get_products_table() -> Table:
    """Return the products (inventory) table handle."""
    return products_table


def get_stock_movements_table() -> Table:
    """Return the stock movements ledger table handle."""
    return stock_movements_table


def get_stock_reservations_table() -> Table:
    """Return the stock reservations table handle."""
    return stock_reservations_table


def get_carriers_table() -> Table:
    """Return the carriers table handle."""
    return carriers_table


def get_carrier_assignments_table() -> Table:
    """Return the carrier assignments table handle."""
    return carrier_assignments_table


def get_chat_sessions_table() -> Table:
    """Return durable local chat session records."""
    return chat_sessions_table


def get_chat_messages_table() -> Table:
    """Return durable local chat message records."""
    return chat_messages_table


# ─────────────────────────────────────────────────────────────────────────
# SQLModel / Supabase (PostgreSQL) — Lazy engine
# ─────────────────────────────────────────────────────────────────────────
# The engine is created on first access (not at import time) so that
# reloader subprocesses (uvicorn --reload) can initialize cleanly.

_engine: object | None = None


def _get_sql_url() -> str:
    url_file = os.getenv("SQL_URL_FILE", "").strip()
    if url_file:
        try:
            url = Path(url_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("SQL_URL_FILE could not be read.") from exc
    else:
        url = os.getenv("SQL_URL")
    if not url:
        raise RuntimeError(
            "La variable de entorno SQL_URL es obligatoria para conectar con "
            "Supabase PostgreSQL. Defínela en el archivo .env"
        )
    return url


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(_get_sql_url(), echo=False)
    return _engine


def init_db() -> None:
    """Create all SQLModel tables in Supabase if they don't exist yet.

    Call this once during application startup (e.g. inside a FastAPI
    ``lifespan`` context manager).
    """
    # The import registers the table models with SQLModel.metadata.
    from src.models.sql_models import (  # noqa: F401
        DeadLetterRow,
        IncidentTable,
        ProfileTable,
        SupplierTable,
        UserTable,
    )
    from src.models.models import (  # noqa: F401
        PendingSKUExit,
        SKU,
        SKUEntry,
        SKUExit,
    )
    from src.models.rfp import (  # noqa: F401
        DepartmentSection,
        RFPFinalDocument,
        RFPNodeTrace,
        RFPDocument,
        RFPTicket,
    )

    SQLModel.metadata.create_all(get_engine())


def get_sql_session() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a **new** SQLModel session per request.

    The session is automatically closed when the request finishes.
    Use it as a dependency on your route handlers::

        from fastapi import Depends
        from sqlmodel import Session

        @router.get("/items")
        def list_items(db: Session = Depends(get_sql_session)):
            ...

    No global session variables are used — each request gets its own
    isolated session.
    """
    with Session(get_engine()) as session:
        yield session
