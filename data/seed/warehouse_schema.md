# Warehouse Schema

The analytics warehouse is the single source of truth for reporting. Tables are
written by Airflow DAGs; nothing else may write to them.

## `revenue`

One row per region per month. Written by `daily_revenue`.

| column        | type    | notes                                  |
|---------------|---------|----------------------------------------|
| `region`      | text    | EMEA, AMER or APAC                     |
| `month`       | text    | `YYYY-MM`                              |
| `revenue_usd` | integer | whole US dollars, already deduplicated |

The grain is region-month. Summing `revenue_usd` without grouping by `month`
double counts across periods, which is the most common reporting mistake.

## `orders_raw`

Landing table for raw orders, written hourly by the `ingest_orders` Spark job.
Retention is 90 days. It is not deduplicated: the same `order_id` can appear
more than once when an upstream retry replays a batch.

## `customers`

Slowly changing dimension, type 2. Always filter on `is_current = true` unless
you deliberately want history; forgetting this inflates customer counts by
roughly a factor of three.
