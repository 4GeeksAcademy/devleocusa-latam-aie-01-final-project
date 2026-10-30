-- Human approval queue for outbound dispatches. Apply before deploying API code.
CREATE TABLE IF NOT EXISTS pending_sku_exits (
    id VARCHAR(36) PRIMARY KEY,
    sku_id VARCHAR(36) NOT NULL REFERENCES sku(id),
    quantity INTEGER NOT NULL CHECK (quantity >= 1),
    requester_uuid VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    approver_uuid VARCHAR(100),
    decision_comment VARCHAR(1000),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    decided_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS ix_pending_sku_exits_sku_id ON pending_sku_exits (sku_id);
CREATE INDEX IF NOT EXISTS ix_pending_sku_exits_status ON pending_sku_exits (status);