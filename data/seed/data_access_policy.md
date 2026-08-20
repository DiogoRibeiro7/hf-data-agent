# Data Access Policy

## Who can query what

Analyst accounts hold `SELECT` on the reporting schema only. Nobody queries the
warehouse with a write-capable role, including during incidents; if a fix needs
a write, it goes through a pull request to the owning DAG.

Service accounts — including the data agent — are read-only by construction.
The agent connects with a role that holds `SELECT` and nothing else, so a
prompt-injected or malformed query cannot modify data even if it slips past the
application's own SQL guard.

## Personal data

`customers` contains personal data. Email and postal address are restricted:
they are excluded from the reporting schema and available only through the
`pii_customers` view, which requires membership of `data-pii-readers`.

Aggregates over restricted columns are still restricted. Do not copy personal
data into a spreadsheet, a notebook output, or a ticket.

## Retention

Raw landing tables are kept for 90 days. Aggregated reporting tables are kept
indefinitely. Deletion requests are handled by the data-governance team within
30 days.
