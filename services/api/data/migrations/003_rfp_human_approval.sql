-- Additive Parte 3 persistence. Existing Part 1/2 rows and artifacts are retained.
ALTER TABLE rfp_department_sections
    ADD COLUMN IF NOT EXISTS approval_status VARCHAR(30) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS approver VARCHAR(200),
    ADD COLUMN IF NOT EXISTS approval_comment TEXT,
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS approval_iteration_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS department_id VARCHAR(30);

CREATE INDEX IF NOT EXISTS ix_rfp_department_sections_department_id
    ON rfp_department_sections (department_id);

CREATE TABLE IF NOT EXISTS rfp_final_documents (
    ticket_id VARCHAR(36) PRIMARY KEY REFERENCES rfp_tickets(id) ON DELETE CASCADE,
    sections TEXT NOT NULL,
    currency VARCHAR(3) NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rfp_node_traces (
    id BIGSERIAL PRIMARY KEY,
    ticket_id VARCHAR(36) NOT NULL REFERENCES rfp_tickets(id) ON DELETE CASCADE,
    department_id VARCHAR(30) NOT NULL,
    thread_id VARCHAR(180) NOT NULL,
    sequence INTEGER NOT NULL,
    node VARCHAR(120) NOT NULL,
    agent VARCHAR(200) NOT NULL,
    input JSONB NOT NULL,
    output JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    UNIQUE (thread_id, sequence)
);
CREATE INDEX IF NOT EXISTS ix_rfp_node_traces_ticket_department
    ON rfp_node_traces (ticket_id, department_id, sequence);
