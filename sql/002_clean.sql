-- 002_clean.sql
-- Clean layer: standardized values, kept next to the raw text, ready for review.

-- Vendor name standardization: what OCR reads -> the name we use.
-- Add a row here for every real supplier.
CREATE TABLE clean.vendor_mapping (
    vendor_raw   TEXT PRIMARY KEY,      -- uppercase, single spaces
    vendor_name  TEXT NOT NULL
);

-- The fake vendors used by the sample receipts
INSERT INTO clean.vendor_mapping (vendor_raw, vendor_name) VALUES
    ('HARBOR FRESH FOODS',      'Harbor Fresh Foods'),
    ('GOLDEN VALLEY PRODUCE',   'Golden Valley Produce'),
    ('SUNRISE MEAT CO.',        'Sunrise Meat Co.'),
    ('METRO RESTAURANT SUPPLY', 'Metro Restaurant Supply');

-- One row per receipt (one per stored image file)
CREATE TABLE clean.receipt (
    receipt_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_id          BIGINT NOT NULL UNIQUE REFERENCES raw.receipt_file (file_id),
    ocr_run_id       BIGINT REFERENCES raw.ocr_run (ocr_run_id),
    vendor_raw       TEXT,               -- as read by OCR
    vendor_name      TEXT,               -- standardized
    receipt_date_raw TEXT,               -- as read by OCR, e.g. 'Jul 12, 2026'
    receipt_date     DATE,               -- standardized
    receipt_number   TEXT,
    subtotal         NUMERIC(12, 2),
    tax              NUMERIC(12, 2),
    total            NUMERIC(12, 2),
    review_status    TEXT NOT NULL DEFAULT 'pending'
                     CHECK (review_status IN ('pending', 'needs_review', 'approved', 'rejected')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per line item on a receipt
CREATE TABLE clean.receipt_line (
    line_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    receipt_id       BIGINT NOT NULL REFERENCES clean.receipt (receipt_id) ON DELETE CASCADE,
    line_no          INTEGER NOT NULL,
    description_raw  TEXT,               -- as read by OCR
    description      TEXT,               -- uppercase, single spaces
    quantity         NUMERIC(12, 3),
    unit_raw         TEXT,
    unit_price       NUMERIC(12, 2),
    line_total       NUMERIC(12, 2),
    UNIQUE (receipt_id, line_no)
);

-- Every manual change made on the review page
CREATE TABLE clean.correction (
    correction_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    receipt_id     BIGINT NOT NULL REFERENCES clean.receipt (receipt_id),
    field_name     TEXT NOT NULL,        -- e.g. 'total' or 'line 3 quantity'
    old_value      TEXT,
    new_value      TEXT,
    corrected_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX receipt_line_receipt_id_idx ON clean.receipt_line (receipt_id);
CREATE INDEX correction_receipt_id_idx ON clean.correction (receipt_id);
