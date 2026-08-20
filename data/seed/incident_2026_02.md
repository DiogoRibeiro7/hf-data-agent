# Incident postmortem — 2026-02-14 revenue understated

## Summary

For eight hours the `revenue` table understated AMER revenue by roughly 12%
because the `ingest_orders` Spark job silently dropped a batch of orders whose
currency code was lowercase.

## Timeline

- 02:00 UTC — `daily_revenue` completed successfully with incomplete input.
- 09:20 UTC — finance noticed AMER figures below forecast.
- 11:45 UTC — root cause identified in the currency normalisation step.
- 13:10 UTC — backfill completed, figures corrected.

## Root cause

The currency filter compared against uppercase codes only. A partner API change
began emitting `usd` instead of `USD`, so those rows failed the filter and were
dropped without an error.

## What we changed

- The currency comparison is now case-insensitive.
- `ingest_orders` fails loudly when it drops more than 0.5% of a batch.
- A freshness and row-count monitor now runs after `daily_revenue`.

## Lesson

A pipeline that succeeds is not the same as a pipeline that is correct. Silent
row loss is the failure mode to design against.
