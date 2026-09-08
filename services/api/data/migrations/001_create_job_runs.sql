-- ============================================================================
-- Migración: 001_create_job_runs.sql
-- Descripción: Tabla transaccional para controlar el ciclo de vida y la
--              idempotencia de scripts nocturnos automatizados.
-- Base de datos: Supabase (PostgreSQL)
-- Fecha: 2026-09-07
-- ============================================================================
-- NOTA: Esta tabla es EXCLUSIVAMENTE para la orquestación del script.
--       NO tiene Foreign Keys ni relaciones con pipeline_runs u otras tablas.
-- ============================================================================

BEGIN;

-- ── 1. Crear la tabla ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS job_runs (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name      TEXT        NOT NULL,
    target_date   DATE        NOT NULL,
    status        TEXT        NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    started_at    TIMESTAMPTZ NULL,
    finished_at   TIMESTAMPTZ NULL,
    error_message TEXT        NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 2. Comentarios de columna (documentación en catálogo) ─────────────────

COMMENT ON TABLE  job_runs IS 'Registro de ejecuciones de scripts nocturnos para orquestación e idempotencia.';
COMMENT ON COLUMN job_runs.id            IS 'Identificador único UUID de la ejecución.';
COMMENT ON COLUMN job_runs.job_name      IS 'Nombre lógico del job (ej. nightly_export).';
COMMENT ON COLUMN job_runs.target_date   IS 'Fecha objetivo del job; garantiza idempotencia por día.';
COMMENT ON COLUMN job_runs.status        IS 'Estado del ciclo: pending → processing → completed | failed.';
COMMENT ON COLUMN job_runs.started_at    IS 'Timestamp de inicio real de la ejecución.';
COMMENT ON COLUMN job_runs.finished_at   IS 'Timestamp de finalización de la ejecución.';
COMMENT ON COLUMN job_runs.error_message IS 'Traza de excepción capturada en caso de fallo.';
COMMENT ON COLUMN job_runs.created_at    IS 'Timestamp de creación del registro.';

-- ── 3. Índice compuesto para validación de idempotencia ────────────────────

CREATE INDEX IF NOT EXISTS idx_job_runs_name_date
    ON job_runs (job_name, target_date);

-- ── 4. Habilitar Row Level Security (RLS) ──────────────────────────────────

ALTER TABLE job_runs ENABLE ROW LEVEL SECURITY;

-- Política para service_role (acceso total desde el backend)
CREATE POLICY "service_role_full_access"
    ON job_runs
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

COMMIT;

-- ============================================================================
-- FIN DE MIGRACIÓN
-- ============================================================================
