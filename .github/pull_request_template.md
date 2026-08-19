## What and why

<!-- What changes, and what problem it solves. Say what breaks if this is wrong. -->

## How it was verified

<!-- Commands run, cases covered. "CI is green" is not sufficient on its own. -->

## Checklist

- [ ] `make check` passes locally (tests, lint, format, types)
- [ ] The offline default path still works end to end (`make seed ingest`, then `/ask`)
- [ ] Tests cover the new behaviour, including its failure modes
- [ ] `CHANGELOG.md` updated under `## [Unreleased]` if user-visible
- [ ] New env vars documented in `.env.example` **and** the README
- [ ] Architecture invariants in `CONTRIBUTING.md` are intact (or the deviation is justified above)
