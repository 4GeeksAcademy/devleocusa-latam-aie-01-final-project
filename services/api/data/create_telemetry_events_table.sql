-- ============================================================
-- TABLA: telemetry_events
-- Descripción: Almacena eventos de telemetría inmutables.
-- Los eventos, una vez insertados, NO pueden ser modificados
-- ni eliminados (se garantiza mediante triggers y RLS).
-- ============================================================

-- ----------------------------------------------------------
-- 1. Creación de la tabla
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS telemetry_events (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      VARCHAR(255)    NOT NULL,
    timestamp       TIMESTAMPTZ     NOT NULL DEFAULT now(),
    source          VARCHAR(255),                          -- opcional: origen del evento
    severity        VARCHAR(50)     DEFAULT 'info',        -- opcional: debug, info, warn, error
    payload         JSONB           DEFAULT '{}'::jsonb,   -- datos específicos del evento
    tags            JSONB           DEFAULT '{}'::jsonb,   -- metadatos indexados (GIN)
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now() -- redundante con timestamp, útil para auditoría
);

-- Comentarios a nivel de columna (documentación)
COMMENT ON TABLE  telemetry_events                     IS 'Eventos de telemetría inmutables del sistema.';
COMMENT ON COLUMN telemetry_events.id                  IS 'Identificador único del evento (UUID v4).';
COMMENT ON COLUMN telemetry_events.event_type          IS 'Tipo de evento (ej: page_view, api_call, error).';
COMMENT ON COLUMN telemetry_events.timestamp           IS 'Marca de tiempo del evento (timezone-aware).';
COMMENT ON COLUMN telemetry_events.source              IS 'Origen o servicio que emitió el evento.';
COMMENT ON COLUMN telemetry_events.severity            IS 'Nivel de severidad (debug, info, warn, error).';
COMMENT ON COLUMN telemetry_events.payload             IS 'Cuerpo principal del evento en formato JSON.';
COMMENT ON COLUMN telemetry_events.tags                IS 'Metadatos planos indexados con GIN (JSONB).';
COMMENT ON COLUMN telemetry_events.created_at          IS 'Momento en que el registro fue persistido.';

-- ----------------------------------------------------------
-- 2. Índices
-- ----------------------------------------------------------

-- Índice B-tree estándar para filtros por rango de tiempo
CREATE INDEX IF NOT EXISTS idx_telemetry_events_timestamp
    ON telemetry_events (timestamp DESC);

-- Índice B-tree para filtros exactos por tipo de evento
CREATE INDEX IF NOT EXISTS idx_telemetry_events_event_type
    ON telemetry_events (event_type);

-- Índice GIN sobre el JSONB tags: permite consultas como
--   WHERE tags @> '{"env": "production"}'
--   WHERE tags ? 'tenant_id'
--   WHERE tags ?| ARRAY['region', 'version']
CREATE INDEX IF NOT EXISTS idx_telemetry_events_tags_gin
    ON telemetry_events USING GIN (tags);

-- Índice GIN opcional sobre payload si se requiere buscar dentro de él
-- CREATE INDEX IF NOT EXISTS idx_telemetry_events_payload_gin
--     ON telemetry_events USING GIN (payload);

-- ----------------------------------------------------------
-- 3. Inmutabilidad — Trigger BEFORE UPDATE/DELETE
--    Rechaza cualquier modificación o borrado a nivel de
--    fila, incluso para superusuarios.
-- -----------------------------------------------------------

CREATE OR REPLACE FUNCTION reject_telemetry_mutation()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Eventos de telemetría son inmutables: no se permite UPDATE (id: %)', OLD.id
            USING HINT = 'Inserte un nuevo evento en lugar de modificar uno existente.';
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Eventos de telemetría son inmutables: no se permite DELETE (id: %)', OLD.id
            USING HINT = 'Los eventos no pueden ser eliminados. Considere una retención por TTL si es necesario.';
    END IF;
    RETURN NULL; -- no retorna NEW, cancelando la operación
END;
$$;

COMMENT ON FUNCTION reject_telemetry_mutation()
    IS 'Trigger que impide UPDATE o DELETE sobre telemetry_events.';

-- Aplicar el trigger a la tabla
DROP TRIGGER IF EXISTS trg_telemetry_events_immutable ON telemetry_events;

CREATE TRIGGER trg_telemetry_events_immutable
    BEFORE UPDATE OR DELETE
    ON telemetry_events
    FOR EACH ROW
    EXECUTE FUNCTION reject_telemetry_mutation();

-- ----------------------------------------------------------
-- 4. Protección adicional vía RLS (Row-Level Security)
--    Útil en entornos multi-tenant o cuando se integra con
--    Supabase. Refuerza la inmutabilidad incluso si el
--    trigger es omitido accidentalmente.
-- -----------------------------------------------------------

-- Habilitar RLS (idempotente)
ALTER TABLE telemetry_events ENABLE ROW LEVEL SECURITY;

-- Política: solo INSERT y SELECT están permitidos.
-- Cualquier intento de UPDATE o DELETE es rechazado por RLS.
DROP POLICY IF EXISTS telemetry_events_immutable_policy ON telemetry_events;

CREATE POLICY telemetry_events_immutable_policy
    ON telemetry_events
    AS PERMISSIVE
    FOR ALL
    TO public
    USING (TRUE)
    WITH CHECK (TRUE);

-- Sobrescribimos: denegar UPDATE
DROP POLICY IF EXISTS telemetry_events_no_update ON telemetry_events;

CREATE POLICY telemetry_events_no_update
    ON telemetry_events
    AS RESTRICTIVE
    FOR UPDATE
    TO public
    USING (FALSE);  -- nunca permite UPDATE

-- Sobrescribimos: denegar DELETE
DROP POLICY IF EXISTS telemetry_events_no_delete ON telemetry_events;

CREATE POLICY telemetry_events_no_delete
    ON telemetry_events
    AS RESTRICTIVE
    FOR DELETE
    TO public
    USING (FALSE);  -- nunca permite DELETE

-- ----------------------------------------------------------
-- 5. (Opcional) Trigger de auditoría: persistir intentos de
--    modificación en una tabla separada (requiere crear
--    telemetry_events_audit_log primero).
-- -----------------------------------------------------------
-- Descomentar si se desea auditar intentos de violación:
--
-- CREATE TABLE IF NOT EXISTS telemetry_events_audit_log (
--     id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
--     event_id    UUID,
--     operation   TEXT NOT NULL,    -- 'UPDATE' o 'DELETE'
--     attempted_at TIMESTAMPTZ DEFAULT now(),
--     old_data    JSONB,
--     attempted_by TEXT DEFAULT current_user
-- );
--
-- CREATE OR REPLACE FUNCTION audit_telemetry_mutation()
--     RETURNS TRIGGER
--     LANGUAGE plpgsql
--     AS $$
-- BEGIN
--     INSERT INTO telemetry_events_audit_log (event_id, operation, old_data)
--     VALUES (OLD.id, TG_OP, row_to_json(OLD)::jsonb);
--     RAISE EXCEPTION 'Operación % bloqueada y auditada.', TG_OP;
-- END;
-- $$;
--
-- DROP TRIGGER IF EXISTS trg_telemetry_events_audit ON telemetry_events;
-- CREATE TRIGGER trg_telemetry_events_audit
--     BEFORE UPDATE OR DELETE ON telemetry_events
--     FOR EACH ROW EXECUTE FUNCTION audit_telemetry_mutation();

-- ============================================================
-- FIN DEL SCRIPT
-- ============================================================