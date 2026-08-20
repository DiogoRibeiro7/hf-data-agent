# Airflow Operations

All scheduled pipelines run on the shared Airflow cluster. The `data-platform`
team owns the scheduler; individual DAGs are owned by the team named in the
DAG's `owner` tag.

## Schedules

| DAG              | schedule        | owner          |
|------------------|-----------------|----------------|
| `ingest_orders`  | hourly, :15     | data-platform  |
| `daily_revenue`  | daily, 02:00 UTC| data-platform  |
| `finance_export` | daily, 06:00 UTC| finance-eng    |
| `churn_features` | daily, 04:00 UTC| ml-platform    |

## Retry policy

Every DAG retries three times with exponential backoff starting at five
minutes. A task that exhausts its retries pages the owning team, not
data-platform, unless the failure is in the scheduler itself.

## Backfills

Backfills must be run with `--reset-dagruns` and a explicit date range. Never
backfill `daily_revenue` past 90 days: the `orders_raw` retention window is 90
days, so older runs silently produce empty partitions rather than failing.

## Pausing

Pausing a DAG does not cancel in-flight task instances. Clear the running tasks
first, then pause, or the next scheduler heartbeat will resume them.
