"""Tests for the reporting module — store, models, and router.

Tests cover:
  - Pipeline execution store (save / get last execution)
  - KPI store (save / get / filter)
  - Router endpoints via TestClient (status, run, kpis, auth)
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from tinydb import TinyDB

# ── Bootstrap test env ──────────────────────────────────────────────────

_TEST_DIR = tempfile.mkdtemp(prefix="trackflow_reporting_tests_")
os.environ.setdefault("REPORTING_DB_PATH", os.path.join(_TEST_DIR, "reporting.json"))
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-reporting-tests")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """Create a FastAPI TestClient with the full app."""
    from src.fastapi_server import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_token(client):
    """Get a valid JWT token for the admin user."""
    resp = client.post(
        "/auth/login",
        json={"email": "admin@trackflow.com", "password": "admin123"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


# ======================================================================
# 1. Store tests
# ======================================================================


class TestPipelineExecutionStore:
    """Tests for save_last_execution / get_last_execution."""

    def setup_method(self):
        from reporting.store import _pipeline_table
        _pipeline_table.truncate()

    def test_save_and_get_last_execution(self):
        """Happy path: save metadata → retrieve it."""
        from reporting.store import get_last_execution, save_last_execution

        metadata = {
            "hora_inicio": "2026-09-03T14:00:00+00:00",
            "hora_fin": "2026-09-03T14:05:00+00:00",
            "duracion_segundos": 300.0,
            "registros_extraidos": 6,
            "estado_final": "Completed",
            "flow_run_id": "abc-123",
            "errores": [],
        }
        save_last_execution(metadata)
        retrieved = get_last_execution()
        assert retrieved is not None
        assert retrieved["hora_inicio"] == "2026-09-03T14:00:00+00:00"
        assert retrieved["flow_run_id"] == "abc-123"
        assert retrieved["errores"] == []

    def test_get_last_execution_when_empty(self):
        """Boundary: no executions yet → returns None."""
        from reporting.store import get_last_execution
        assert get_last_execution() is None

    def test_save_overwrites_previous(self):
        """Boundary: save_last_execution replaces previous record."""
        from reporting.store import get_last_execution, save_last_execution

        save_last_execution({"flow_run_id": "first", "errores": []})
        save_last_execution({"flow_run_id": "second", "errores": []})
        retrieved = get_last_execution()
        assert retrieved["flow_run_id"] == "second"

    def test_save_with_errors(self):
        """Failure mode: metadata with errores list."""
        from reporting.store import get_last_execution, save_last_execution

        metadata = {
            "hora_inicio": "2026-09-03T14:00:00+00:00",
            "hora_fin": "2026-09-03T14:05:00+00:00",
            "duracion_segundos": 300.0,
            "registros_extraidos": 6,
            "estado_final": "Completed",
            "flow_run_id": "abc-123",
            "errores": ["notificar_estado failed: Connection refused"],
        }
        save_last_execution(metadata)
        retrieved = get_last_execution()
        assert len(retrieved["errores"]) == 1
        assert "Connection refused" in retrieved["errores"][0]


class TestKPIStore:
    """Tests for save_kpi_record / get_all_kpi_records."""

    def setup_method(self):
        from reporting.store import _kpis_table
        _kpis_table.truncate()

    def _sample_kpi(self, fecha="2026-09-03", corrida="run-001"):
        return {
            "fecha_reporte": fecha,
            "id_corrida": corrida,
            "timestamp": "2026-09-03T14:00:00+00:00",
            "periodo": fecha,
            "volumen_envios": {"total": 2, "por_almacen": {"los-angeles": 1, "zaragoza": 1}},
            "tasa_entrega_tiempo": {"porcentaje": 50.0, "entregas_on_time": 1, "entregas_totales": 2},
            "devoluciones": {"volumen": 2, "tasa_porcentaje": 100.0},
        }

    def test_save_and_get_kpi(self):
        """Happy path: save KPI → retrieve it."""
        from reporting.store import get_all_kpi_records, save_kpi_record

        kpi = self._sample_kpi()
        save_kpi_record(kpi)
        records = get_all_kpi_records()
        assert len(records) == 1
        assert records[0]["fecha_reporte"] == "2026-09-03"
        assert records[0]["id_corrida"] == "run-001"

    def test_get_kpis_empty(self):
        """Boundary: no KPI records yet → empty list."""
        from reporting.store import get_all_kpi_records
        assert get_all_kpi_records() == []

    def test_upsert_replaces_existing(self):
        """Boundary: same (fecha_reporte, id_corrida) → upsert replaces."""
        from reporting.store import get_all_kpi_records, save_kpi_record

        kpi1 = self._sample_kpi(corrida="run-001")
        kpi2 = self._sample_kpi(corrida="run-001")  # Same key
        kpi2["volumen_envios"]["total"] = 5

        save_kpi_record(kpi1)
        save_kpi_record(kpi2)
        records = get_all_kpi_records()
        assert len(records) == 1  # Upsert, not duplicate
        assert records[0]["volumen_envios"]["total"] == 5

    def test_filter_by_fecha_reporte(self):
        """Filter: get_all_kpi_records with fecha_reporte."""
        from reporting.store import get_all_kpi_records, save_kpi_record

        save_kpi_record(self._sample_kpi(fecha="2026-09-03", corrida="run-001"))
        save_kpi_record(self._sample_kpi(fecha="2026-09-10", corrida="run-002"))

        records = get_all_kpi_records(fecha_reporte="2026-09-03")
        assert len(records) == 1
        assert records[0]["id_corrida"] == "run-001"

    def test_filter_by_id_corrida(self):
        """Filter: get_all_kpi_records with id_corrida."""
        from reporting.store import get_all_kpi_records, save_kpi_record

        save_kpi_record(self._sample_kpi(corrida="run-001"))
        save_kpi_record(self._sample_kpi(corrida="run-002"))

        records = get_all_kpi_records(id_corrida="run-002")
        assert len(records) == 1
        assert records[0]["id_corrida"] == "run-002"

    def test_limit(self):
        """Boundary: limit parameter caps results."""
        from reporting.store import get_all_kpi_records, save_kpi_record

        for i in range(5):
            save_kpi_record(self._sample_kpi(corrida=f"run-{i:03d}"))

        records = get_all_kpi_records(limit=3)
        assert len(records) == 3

    def test_filter_combined(self):
        """Combined filter: fecha_reporte + id_corrida."""
        from reporting.store import get_all_kpi_records, save_kpi_record

        save_kpi_record(self._sample_kpi(fecha="2026-09-03", corrida="run-001"))
        save_kpi_record(self._sample_kpi(fecha="2026-09-03", corrida="run-002"))

        records = get_all_kpi_records(fecha_reporte="2026-09-03", id_corrida="run-001")
        assert len(records) == 1
        assert records[0]["id_corrida"] == "run-001"


# ======================================================================
# 2. Models tests
# ======================================================================


class TestPipelineExecutionMetadata:
    """Tests for PipelineExecutionMetadata Pydantic model."""

    def test_valid_metadata(self):
        """Happy path: all fields provided."""
        from reporting.models import PipelineExecutionMetadata

        m = PipelineExecutionMetadata(
            hora_inicio="2026-09-03T14:00:00+00:00",
            hora_fin="2026-09-03T14:05:00+00:00",
            duracion_segundos=300.0,
            registros_extraidos=6,
            estado_final="Completed",
            flow_run_id="abc-123",
            errores=[],
        )
        assert m.flow_run_id == "abc-123"
        assert m.errores == []

    def test_errores_default_empty_list(self):
        """Boundary: errores defaults to empty list."""
        from reporting.models import PipelineExecutionMetadata

        m = PipelineExecutionMetadata(
            hora_inicio="2026-09-03T14:00:00+00:00",
            hora_fin="2026-09-03T14:05:00+00:00",
        )
        assert m.errores == []

    def test_errores_with_items(self):
        """Failure mode: errores list with items."""
        from reporting.models import PipelineExecutionMetadata

        m = PipelineExecutionMetadata(
            hora_inicio="2026-09-03T14:00:00+00:00",
            hora_fin="2026-09-03T14:05:00+00:00",
            errores=["notificar_estado failed: Connection refused"],
        )
        assert len(m.errores) == 1


class TestExecutiveKPIs:
    """Tests for ExecutiveKPIs Pydantic model."""

    def test_valid_kpi(self):
        """Happy path: all fields provided."""
        from reporting.models import ExecutiveKPIs, VolumenEnvios, TasaEntregaTiempo, Devoluciones

        kpi = ExecutiveKPIs(
            fecha_reporte="2026-09-03",
            id_corrida="run-001",
            timestamp="2026-09-03T14:00:00+00:00",
            periodo="2026-09-03",
            volumen_envios=VolumenEnvios(total=2, por_almacen={"los-angeles": 1, "zaragoza": 1}),
            tasa_entrega_tiempo=TasaEntregaTiempo(porcentaje=50.0, entregas_on_time=1, entregas_totales=2),
            devoluciones=Devoluciones(volumen=2, tasa_porcentaje=100.0),
        )
        assert kpi.fecha_reporte == "2026-09-03"
        assert kpi.volumen_envios.total == 2


# ======================================================================
# 3. Router integration tests (via TestClient)
# ======================================================================


class TestGetPipelineStatus:
    """Tests for GET /reporting/status."""

    def setup_method(self):
        from reporting.store import _pipeline_table, _kpis_table
        _pipeline_table.truncate()
        _kpis_table.truncate()

    def test_status_when_no_execution(self, client, admin_token):
        """Boundary: no executions yet → ultima_ejecucion is None."""
        resp = client.get("/reporting/status", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["pipeline"] == "trackflow_pipeline_telemetria"
        assert data["ultima_ejecucion"] is None
        assert len(data["tablas_destino"]) > 0

    def test_status_requires_auth(self, client):
        """Failure mode: no token → 401."""
        resp = client.get("/reporting/status")
        assert resp.status_code == 401


class TestTriggerPipeline:
    """Tests for POST /reporting/run."""

    def setup_method(self):
        from reporting.store import _pipeline_table, _kpis_table
        _pipeline_table.truncate()
        _kpis_table.truncate()

    def test_trigger_requires_auth(self, client):
        """Failure mode: no token → 401."""
        resp = client.post("/reporting/run")
        assert resp.status_code == 401

    @patch("reporting.router.trackflow_pipeline_telemetria")
    def test_trigger_successful_run(self, mock_pipeline, client, admin_token):
        """Happy path: pipeline executes successfully → returns metadata."""
        from reporting.store import _pipeline_table, _kpis_table
        _pipeline_table.truncate()
        _kpis_table.truncate()

        # Mock the pipeline to return a realistic result
        mock_pipeline.return_value = {
            "_metadata": {
                "hora_inicio": "2026-09-03T14:00:00+00:00",
                "hora_fin": "2026-09-03T14:05:00+00:00",
                "duracion_segundos": 300.0,
                "registros_extraidos": 6,
                "estado_final": "Completed",
                "flow_run_id": "abc-123",
                "errores": [],
            },
            "data": {
                "fecha_reporte": "2026-09-03",
                "id_corrida": "mock-run-001",
                "timestamp": "2026-09-03T14:00:00+00:00",
                "periodo": "2026-09-03",
                "volumen_envios": {"total": 2, "por_almacen": {"los-angeles": 1, "zaragoza": 1}},
                "tasa_entrega_tiempo": {"porcentaje": 50.0, "entregas_on_time": 1, "entregas_totales": 2},
                "devoluciones": {"volumen": 2, "tasa_porcentaje": 100.0},
            },
        }

        resp = client.post("/reporting/run", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["status"] == "success"
        assert data["metadata"]["estado_final"] == "Completed"
        assert data["metadata"]["errores"] == []
        assert data["flow_run_id"] is not None

    @patch("reporting.router.trackflow_pipeline_telemetria")
    def test_trigger_pipeline_error(self, mock_pipeline, client, admin_token):
        """Failure mode: pipeline raises RuntimeError → 502."""
        mock_pipeline.side_effect = RuntimeError("Database connection failed")

        resp = client.post("/reporting/run", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 502
        data = resp.json()
        assert "error" in data

    @patch("reporting.router.trackflow_pipeline_telemetria")
    def test_trigger_with_errors_in_metadata(self, mock_pipeline, client, admin_token):
        """Failure mode: pipeline has errores in metadata."""
        from reporting.store import _pipeline_table, _kpis_table
        _pipeline_table.truncate()
        _kpis_table.truncate()

        mock_pipeline.return_value = {
            "_metadata": {
                "hora_inicio": "2026-09-03T14:00:00+00:00",
                "hora_fin": "2026-09-03T14:05:00+00:00",
                "duracion_segundos": 300.0,
                "registros_extraidos": 6,
                "estado_final": "Completed",
                "flow_run_id": "abc-123",
                "errores": ["notificar_estado failed: Connection refused"],
            },
            "data": None,
        }

        resp = client.post("/reporting/run", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["metadata"]["errores"]) == 1
        assert "Connection refused" in data["metadata"]["errores"][0]


class TestGetKPIs:
    """Tests for GET /reporting/kpis."""

    def setup_method(self):
        from reporting.store import _pipeline_table, _kpis_table
        _pipeline_table.truncate()
        _kpis_table.truncate()

    @patch("reporting.router.trackflow_pipeline_telemetria")
    def test_kpis_after_pipeline_run(self, mock_pipeline, client, admin_token):
        """Happy path: KPIs exist after pipeline run."""
        from reporting.store import _pipeline_table, _kpis_table
        _pipeline_table.truncate()
        _kpis_table.truncate()

        mock_pipeline.return_value = {
            "_metadata": {
                "hora_inicio": "2026-09-03T14:00:00+00:00",
                "hora_fin": "2026-09-03T14:05:00+00:00",
                "duracion_segundos": 300.0,
                "registros_extraidos": 6,
                "estado_final": "Completed",
                "flow_run_id": "abc-123",
                "errores": [],
            },
            "data": {
                "fecha_reporte": "2026-09-03",
                "id_corrida": "kpi-test-001",
                "timestamp": "2026-09-03T14:00:00+00:00",
                "periodo": "2026-09-03",
                "volumen_envios": {"total": 2, "por_almacen": {"los-angeles": 1, "zaragoza": 1}},
                "tasa_entrega_tiempo": {"porcentaje": 50.0, "entregas_on_time": 1, "entregas_totales": 2},
                "devoluciones": {"volumen": 2, "tasa_porcentaje": 100.0},
            },
        }

        # Run pipeline first
        resp = client.post("/reporting/run", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200

        # Now query KPIs
        resp = client.get("/reporting/kpis", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert data["registros"][0]["fecha_reporte"] == "2026-09-03"

    def test_kpis_empty(self, client, admin_token):
        """Boundary: no KPI records → empty list."""
        from reporting.store import _kpis_table
        _kpis_table.truncate()

        resp = client.get("/reporting/kpis", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["registros"] == []

    def test_kpis_requires_auth(self, client):
        """Failure mode: no token → 401."""
        resp = client.get("/reporting/kpis")
        assert resp.status_code == 401


# ======================================================================
# 4. Cleanup
# ======================================================================


def pytest_unconfigure():
    """Remove the temporary test directory."""
    shutil.rmtree(_TEST_DIR, ignore_errors=True)