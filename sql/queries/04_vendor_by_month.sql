-- Spend per vendor per month, with the change vs. the vendor's previous month
SELECT v.vendor_name,
       d.year,
       d.month,
       sum(f.line_total) AS spend,
       sum(f.line_total) - lag(sum(f.line_total)) OVER (
           PARTITION BY v.vendor_name ORDER BY d.year, d.month
       ) AS change_vs_previous_month
FROM mart.fact_purchase_line f
JOIN mart.dim_vendor v ON v.vendor_key = f.vendor_key
JOIN mart.dim_date d ON d.date_key = f.date_key
GROUP BY v.vendor_name, d.year, d.month
ORDER BY v.vendor_name, d.year, d.month;
