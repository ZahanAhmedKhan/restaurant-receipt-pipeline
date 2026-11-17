-- Average receipt value and lines per receipt, per vendor
WITH receipt_totals AS (
    SELECT f.receipt_id, f.vendor_key,
           sum(f.line_total) AS receipt_spend,
           count(*) AS lines
    FROM mart.fact_purchase_line f
    GROUP BY f.receipt_id, f.vendor_key
)
SELECT v.vendor_name,
       count(*) AS receipts,
       round(avg(rt.receipt_spend), 2) AS avg_receipt_spend,
       round(avg(rt.lines), 1) AS avg_lines_per_receipt
FROM receipt_totals rt
JOIN mart.dim_vendor v ON v.vendor_key = rt.vendor_key
GROUP BY v.vendor_name
ORDER BY avg_receipt_spend DESC;
