# Revenue Pipeline Runbook

The `daily_revenue` Airflow DAG aggregates raw orders into the `revenue` table in
the warehouse every night at 02:00 UTC. Owner: data-platform team.

If the DAG fails, check the `orders_raw` freshness first — upstream Spark job
`ingest_orders` must finish before `daily_revenue` starts.

The `revenue` table has columns: region, month, revenue_usd. Quarterly board
numbers are sourced from this table, not from the spreadsheet exports.
