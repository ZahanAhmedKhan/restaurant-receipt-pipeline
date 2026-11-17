-- 006_price_views.sql
-- Price history per item per vendor, and alerts for big price increases.

-- Settings the views need. load_mart.py copies PRICE_ALERT_THRESHOLD_PCT from .env
-- into this table on every mart build.
CREATE TABLE mart.setting (
    name   TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
INSERT INTO mart.setting (name, value) VALUES ('price_alert_threshold_pct', '10');

-- One row per item, vendor and purchase date: the price per standard unit
-- (weighted if the item was bought more than once that day), and the change
-- vs. the previous purchase of the same item from the same vendor.
CREATE VIEW mart.v_price_history AS
WITH purchases AS (
    SELECT i.item_name,
           i.standard_unit,
           v.vendor_name,
           d.full_date AS purchase_date,
           sum(f.line_total) / sum(f.standard_quantity) AS unit_price,
           sum(f.standard_quantity) AS quantity
    FROM mart.fact_purchase_line f
    JOIN mart.dim_item i   ON i.item_key = f.item_key
    JOIN mart.dim_vendor v ON v.vendor_key = f.vendor_key
    JOIN mart.dim_date d   ON d.date_key = f.date_key
    WHERE i.item_name <> 'UNMAPPED'
      AND d.full_date IS NOT NULL
      AND f.standard_quantity > 0
      AND f.line_total IS NOT NULL
    GROUP BY i.item_name, i.standard_unit, v.vendor_name, d.full_date
)
SELECT item_name,
       standard_unit,
       vendor_name,
       purchase_date,
       round(unit_price, 4) AS unit_price,
       quantity,
       lag(purchase_date) OVER w AS previous_date,
       round(lag(unit_price) OVER w, 4) AS previous_price,
       round(100 * (unit_price - lag(unit_price) OVER w) / lag(unit_price) OVER w, 1) AS pct_change
FROM purchases
WINDOW w AS (PARTITION BY item_name, vendor_name ORDER BY purchase_date);

-- Purchases where the price rose more than the threshold since the previous purchase
CREATE VIEW mart.v_price_alerts AS
SELECT h.*
FROM mart.v_price_history h
WHERE h.pct_change > (
    SELECT value::numeric FROM mart.setting WHERE name = 'price_alert_threshold_pct'
);
