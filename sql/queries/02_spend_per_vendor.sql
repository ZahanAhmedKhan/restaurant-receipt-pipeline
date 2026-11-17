-- Spend per vendor, with share of total spend
SELECT v.vendor_name,
       sum(f.line_total) AS spend,
       round(100.0 * sum(f.line_total) / sum(sum(f.line_total)) OVER (), 1) AS pct_of_total,
       count(DISTINCT f.receipt_id) AS receipts
FROM mart.fact_purchase_line f
JOIN mart.dim_vendor v ON v.vendor_key = f.vendor_key
GROUP BY v.vendor_name
ORDER BY spend DESC;
