-- 004_mart.sql
-- Mart layer: star schema for analytics. Built ONLY from approved receipts
-- by src/load_mart.py (safe to rebuild any time).

CREATE TABLE mart.dim_vendor (
    vendor_key   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vendor_name  TEXT NOT NULL UNIQUE
);

CREATE TABLE mart.dim_item (
    item_key       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_name      TEXT NOT NULL UNIQUE,        -- normalized name, e.g. 'chicken breast'
    category       TEXT,
    standard_unit  TEXT CHECK (standard_unit IN ('lb', 'kg', 'each', 'L'))
);

-- Lines whose description has no mapping rule yet point to this item
INSERT INTO mart.dim_item (item_name, category, standard_unit)
VALUES ('UNMAPPED', NULL, NULL);

CREATE TABLE mart.dim_date (
    date_key     INTEGER PRIMARY KEY,           -- YYYYMMDD, e.g. 20260614; 0 = unknown
    full_date    DATE UNIQUE,
    year         INTEGER,
    month        INTEGER,
    month_name   TEXT,
    week         INTEGER,                       -- ISO week number
    day_of_week  TEXT
);

-- "Unknown date" row, for approved receipts without a readable date
INSERT INTO mart.dim_date (date_key, full_date, month_name, day_of_week)
VALUES (0, NULL, 'Unknown', 'Unknown');

-- Grain: one line item on one approved receipt
CREATE TABLE mart.fact_purchase_line (
    purchase_key         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    line_id              BIGINT NOT NULL UNIQUE,   -- lineage: clean.receipt_line
    receipt_id           BIGINT NOT NULL,          -- lineage: clean.receipt
    vendor_key           INTEGER NOT NULL REFERENCES mart.dim_vendor (vendor_key),
    item_key             INTEGER NOT NULL REFERENCES mart.dim_item (item_key),
    date_key             INTEGER NOT NULL REFERENCES mart.dim_date (date_key),
    quantity             NUMERIC(12, 3),
    standard_quantity    NUMERIC(14, 3),           -- in the item's standard unit (M6.1)
    line_total           NUMERIC(12, 2),
    unit_price_standard  NUMERIC(14, 4)            -- price per standard unit (M6.1)
);

CREATE INDEX fact_vendor_idx ON mart.fact_purchase_line (vendor_key);
CREATE INDEX fact_item_idx   ON mart.fact_purchase_line (item_key);
CREATE INDEX fact_date_idx   ON mart.fact_purchase_line (date_key);
