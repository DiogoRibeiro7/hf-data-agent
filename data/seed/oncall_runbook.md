# On-call Runbook

## Rotation

The data-platform on-call rotation is weekly, handing over Monday at 10:00
Lisbon time. The current on-call is listed in the `#data-platform-oncall` Slack
channel topic.

## Paging

Pages come from Airflow task failures and from freshness monitors. A page is
expected to be acknowledged within 15 minutes during business hours and 30
minutes overnight.

## Escalation

Escalate to the data-platform lead after 60 minutes without a path forward, or
immediately if the incident affects finance reporting during month-end close.

## Common first steps

1. Check whether the scheduler itself is healthy before investigating a DAG.
2. Check upstream freshness: most `daily_revenue` failures are actually
   `orders_raw` arriving late.
3. Do not rerun a failed task before reading its log; reruns of a partially
   written task can duplicate rows in landing tables.
