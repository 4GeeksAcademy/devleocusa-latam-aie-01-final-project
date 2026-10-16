-- Parte 2 proposal-generation artifacts; existing Part 1 rows remain valid.
ALTER TABLE rfp_tickets
    ADD COLUMN IF NOT EXISTS proposal_completed_at TIMESTAMPTZ;

ALTER TABLE rfp_department_sections
    ADD COLUMN IF NOT EXISTS proposal_draft TEXT,
    ADD COLUMN IF NOT EXISTS evaluation_result TEXT,
    ADD COLUMN IF NOT EXISTS iteration_count INTEGER NOT NULL DEFAULT 0;

-- Status values are text-backed in SQLModel; no enum/check constraint changes needed.
