-- 003_dq.sql
-- Data quality: one row per check per receipt.
-- Rerunning the checks for a receipt replaces its previous results,
-- so this table always shows the checks for the receipt's current values.

CREATE TABLE dq.check_result (
    check_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    receipt_id  BIGINT      NOT NULL REFERENCES clean.receipt (receipt_id) ON DELETE CASCADE,
    check_name  TEXT        NOT NULL,
    passed      BOOLEAN     NOT NULL,
    details     TEXT,                     -- short reason, never the full receipt
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (receipt_id, check_name)
);

CREATE INDEX check_result_failed_idx ON dq.check_result (check_name) WHERE NOT passed;
