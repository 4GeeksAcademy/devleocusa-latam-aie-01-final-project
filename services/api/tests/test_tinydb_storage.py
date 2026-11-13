"""Regression tests for concurrent access to the shared TinyDB file."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from tinydb import Query, TinyDB

from src.database import LockedTable, ThreadSafeJSONStorage


def test_concurrent_table_writes_do_not_expose_partial_json(tmp_path):
    """Parallel endpoint-style operations must not read during a file write."""
    db = TinyDB(tmp_path / "concurrent.json", storage=ThreadSafeJSONStorage)
    db.table_class = LockedTable
    table = db.table("records")
    worker_count = 8
    records_per_worker = 50

    def write_records(worker_id: int) -> None:
        for record_id in range(records_per_worker):
            table.insert({"worker": worker_id, "record": record_id})
            # Reads happen concurrently with writes in other request threads.
            table.search(Query().worker == worker_id)

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            list(executor.map(write_records, range(worker_count)))

        assert len(table) == worker_count * records_per_worker
    finally:
        db.close()


def test_empty_tinydb_file_is_recovered_as_empty_database(tmp_path):
    db_path = tmp_path / "empty.json"
    db_path.write_text("", encoding="utf-8")
    db = TinyDB(db_path, storage=ThreadSafeJSONStorage)
    try:
        assert db.table("records").all() == []
        db.table("records").insert({"value": "saved"})
        assert db.table("records").all()[0]["value"] == "saved"
    finally:
        db.close()


def test_nonempty_corrupt_tinydb_file_is_not_silently_discarded(tmp_path):
    db_path = tmp_path / "corrupt.json"
    db_path.write_text("{invalid json", encoding="utf-8")

    db = TinyDB(db_path, storage=ThreadSafeJSONStorage)
    db.table_class = LockedTable
    try:
        with pytest.raises(ValueError):
            db.table("records").all()
    finally:
        db.close()
