-- 007_supplier_comparison.sql
-- Compare our suppliers' prices for items we buy from 2+ of them.
--
-- ESTIMATED savings only: it ignores delivery fees, order minimums, quality
-- and availability. It answers "what if we had paid the cheapest latest price?"

-- One row per item per supplier
CREATE VIEW mart.v_supplier_comparison AS
WITH latest AS (
    -- Each supplier's most recent price for each item
    SELECT DISTINCT ON (item_name, vendor_name)
           item_name, standard_unit, vendor_name,
           purchase_date AS latest_date,
           unit_price    AS latest_price
    FROM mart.v_price_history
    ORDER BY item_name, vendor_name, purchase_date DESC
),
compared AS (
    -- Only items bought from at least two suppliers
    SELECT l.*,
           count(*) OVER (PARTITION BY item_name) AS suppliers,
           min(latest_price) OVER (PARTITION BY item_name) AS cheapest_price,
           first_value(vendor_name) OVER (
               PARTITION BY item_name ORDER BY latest_price, vendor_name
           ) AS cheapest_vendor
    FROM latest l
),
months AS (
    -- Number of calendar months that have approved purchases
    SELECT count(DISTINCT d.year * 100 + d.month) AS n
    FROM mart.fact_purchase_line f
    JOIN mart.dim_date d ON d.date_key = f.date_key
    WHERE d.full_date IS NOT NULL
),
bought AS (
    -- How much of each item we bought from each supplier (standard units)
    SELECT item_name, vendor_name, sum(quantity) AS total_quantity
    FROM mart.v_price_history
    GROUP BY item_name, vendor_name
)
SELECT c.item_name,
       c.standard_unit,
       c.vendor_name,
       c.latest_date,
       c.latest_price,
       c.cheapest_vendor,
       c.cheapest_price,
       c.latest_price - c.cheapest_price AS price_difference,
       round(b.total_quantity / NULLIF(m.n, 0), 3) AS avg_monthly_quantity,
       round(b.total_quantity / NULLIF(m.n, 0) * (c.latest_price - c.cheapest_price), 2)
           AS estimated_monthly_savings
FROM compared c
JOIN bought b ON b.item_name = c.item_name AND b.vendor_name = c.vendor_name
CROSS JOIN months m
WHERE c.suppliers >= 2;

-- One row per item: total ESTIMATED monthly savings if every purchase of it
-- had been at the cheapest supplier's latest price
CREATE VIEW mart.v_supplier_savings AS
SELECT item_name,
       standard_unit,
       count(*) AS suppliers,
       min(cheapest_vendor) AS cheapest_vendor,
       min(cheapest_price) AS cheapest_price,
       sum(estimated_monthly_savings) AS estimated_monthly_savings
FROM mart.v_supplier_comparison
GROUP BY item_name, standard_unit;
