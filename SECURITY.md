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

### The HTTP API supports bearer authentication; the MCP transport does not

`POST /ask` and `POST /tool` require a bearer token when `DA_API_TOKEN` is set,
compared in constant time. `GET /health` stays reachable without one so probes
work, but withholds the backend and knowledge-base detail from anonymous
callers.

Authentication is **off** when `DA_API_TOKEN` is empty, so that the offline
quickstart needs no configuration. The bind address carries the safety instead:

- `DA_API_HOST` defaults to `127.0.0.1`.
- Startup **refuses** to bind a non-loopback interface without a token, unless
  `DA_ALLOW_UNAUTHENTICATED=true` declares the port protected by something else.

The container image sets `DA_API_HOST=0.0.0.0` because `-p` cannot reach a
loopback bind, so running it requires one of those two decisions explicitly.

The remote MCP transport takes the **same** token. The MCP library's own auth
is an OAuth resource-server model — it rejects a token verifier unless given an
issuer URL and a resource server URL — and this project authenticates with one
shared secret, so the gate sits in front of the transport instead
(`mcp/auth.py`) rather than inventing an OAuth issuer to satisfy the library.

That gate is applied by the `mcp_remote` entrypoint. Serving
`build_mcp().streamable_http_app()` yourself, or running `mcp_local` over stdio,
does not go through it — stdio inherits the trust of whoever launched the
process, which is the usual MCP model.

`DA_MCP_HOST` defaults to loopback and startup refuses a routable bind with
neither a token nor `DA_ALLOW_UNAUTHENTICATED=true`.

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
