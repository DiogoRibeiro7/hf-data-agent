# Security Policy

## Supported versions

This project is pre-1.0. Only the tip of `main` receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through
[GitHub Security Advisories](https://github.com/DiogoRibeiro7/hf-data-agent/security/advisories/new).
Expect an acknowledgement within 72 hours and an assessment within 7 days.

## Threat model and known limitations

This is an agent that puts a language model in front of your data platform.
Read this section before exposing it beyond localhost.

### The API and the MCP transports are unauthenticated

`POST /ask`, `POST /tool` and the remote MCP transport ship with **no
authentication**. `DA_API_HOST` also defaults to `0.0.0.0`, which binds every
interface. Anyone who can reach the port can query your knowledge base and your
warehouse.

Before deploying anywhere shared, put the service behind an authenticating
reverse proxy or gateway, and bind it narrowly (`DA_API_HOST=127.0.0.1`) when it
only needs to serve a local client.

### SQL execution is guarded, but the guard is not a sandbox

`warehouse_query` runs caller-supplied SQL. It is protected by a statement guard
(`datasources.sql_guard`) that permits a single read-only statement, rejects
DDL/DML and multi-statement payloads, and enforces a row limit.

That guard is a safety net against an LLM or a careless caller doing something
destructive. It is **not** a defence against a determined attacker — SQL dialects
are large and parsing them defensively is not a solved problem. The real control
is the database itself:

- Connect with a **read-only database user** that has `SELECT` and nothing else.
- Grant that user access only to the schemas the agent legitimately needs.
- Prefer a read replica over the primary.

`DA_WAREHOUSE_ALLOWED_TABLES` additionally restricts which tables may be named.

### Prompt injection reaches your tools

Content ingested into the knowledge base is fed to the model as context, and the
model's output drives tool calls. A malicious document in an ingested source can
therefore attempt to steer the agent. Treat every ingestion source as
semi-trusted, and rely on the database-level permissions above rather than on the
model behaving well.

### Secrets

Secrets are read from the environment (`.env` is git-ignored; `.env.example`
holds placeholders only). Never commit a real `DA_HF_TOKEN`, `DA_SLACK_BOT_TOKEN`
or warehouse DSN. Rotate any credential that reaches a log or a shell history.
