-- Top 10 items by spend (items are normalized in M6.1; until then most are UNMAPPED)
SELECT i.item_name,
       i.category,
       sum(f.line_total) AS spend,
       count(*) AS purchase_lines
FROM mart.fact_purchase_line f
JOIN mart.dim_item i ON i.item_key = f.item_key
GROUP BY i.item_name, i.category
ORDER BY spend DESC
LIMIT 10;
