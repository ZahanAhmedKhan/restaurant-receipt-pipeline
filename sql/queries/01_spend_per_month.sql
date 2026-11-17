-- Total spend per month (approved receipts only)
SELECT d.year, d.month, d.month_name,
       sum(f.line_total) AS spend,
       count(DISTINCT f.receipt_id) AS receipts
FROM mart.fact_purchase_line f
JOIN mart.dim_date d ON d.date_key = f.date_key
GROUP BY d.year, d.month, d.month_name
ORDER BY d.year, d.month;
