-- 001_raw.sql
-- Raw layer: exactly what we received. Rows here are never edited by hand.

-- One row per unique image file (unique by SHA-256 hash of its bytes)
CREATE TABLE raw.receipt_file (
    file_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sha256         CHAR(64)    NOT NULL UNIQUE,
    stored_path    TEXT        NOT NULL,          -- e.g. data/raw/<sha256>.jpg
    original_name  TEXT,                          -- label only, never used as a path
    source         TEXT        NOT NULL CHECK (source IN ('inbox', 'upload', 'camera')),
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    status         TEXT        NOT NULL DEFAULT 'new'
                   CHECK (status IN ('new', 'ocr_done', 'parsed', 'failed'))
);

-- One row per OCR attempt on a file (a file can be OCR'd more than once,
-- e.g. with Tesseract and later with Gemini)
CREATE TABLE raw.ocr_run (
    ocr_run_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_id      BIGINT      NOT NULL REFERENCES raw.receipt_file (file_id),
    method       TEXT        NOT NULL CHECK (method IN ('tesseract', 'gemini')),
    raw_text     TEXT,                            -- plain text from Tesseract
    raw_json     JSONB,                           -- structured answer from Gemini
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_ms  INTEGER,
    error        TEXT                             -- error type if OCR failed
);

CREATE INDEX ocr_run_file_id_idx ON raw.ocr_run (file_id);
