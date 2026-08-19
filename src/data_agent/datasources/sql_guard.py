"""Read-only guard for caller-supplied SQL.

`warehouse_query` is reachable from the HTTP API, from MCP clients, and from
whatever the language model decides to emit. None of those are trustworthy
sources of SQL, so a statement is checked before it reaches the engine.

What this does:

* strips comments and string/identifier literals, so the checks below cannot be
  smuggled past inside quotes;
* requires exactly one statement (a trailing semicolon is fine);
* requires it to start with SELECT or WITH;
* rejects destructive verbs anywhere in the statement, which also catches
  data-modifying CTEs such as ``WITH x AS (DELETE ... RETURNING *) SELECT``;
* optionally restricts the tables that may be named;
* appends a LIMIT when the statement has no row cap of its own.

What this is NOT: a sandbox. SQL dialects are large and a keyword blocklist is a
safety net, not a security boundary. Point `DA_WAREHOUSE_DSN` at a database user
that only holds SELECT on the schemas the agent needs. See SECURITY.md.
"""

from __future__ import annotations

import re

__all__ = ["UnsafeSQLError", "enforce_row_limit", "guard_select", "referenced_tables"]


class UnsafeSQLError(ValueError):
    """Raised when a statement is rejected before reaching the database."""


# Verbs that write, change structure, change permissions, or run code. Matched as
# whole words anywhere in the literal-stripped statement.
_FORBIDDEN = frozenset(
    {
        "alter",
        "attach",
        "call",
        "copy",
        "create",
        "delete",
        "detach",
        "drop",
        "exec",
        "execute",
        "grant",
        "insert",
        "into",  # SELECT ... INTO materialises a new table
        "merge",
        "pragma",
        "reindex",
        "rename",
        "replace",
        "revoke",
        "truncate",
        "update",
        "upsert",
        "vacuum",
    }
)

_ALLOWED_HEADS = frozenset({"select", "with"})

# Comments, then single-quoted / double-quoted / backtick-quoted runs.
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_LITERAL = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`[^`]*`")
_WORD = re.compile(r"[a-zA-Z_][a-zA-Z0-9_$]*")
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_$.]*)", re.IGNORECASE)
_HAS_ROW_CAP = re.compile(r"\blimit\b|\bfetch\s+first\b|\bselect\s+top\b", re.IGNORECASE)


def _skeleton(sql: str) -> str:
    """The statement with comments and quoted runs blanked out.

    Quoted runs become a single space rather than vanishing, so that
    ``a'x'b`` cannot fuse into one token.
    """
    without_comments = _COMMENT.sub(" ", sql)
    return _LITERAL.sub(" ", without_comments)


def _split_statements(skeleton: str) -> list[str]:
    return [part for part in skeleton.split(";") if part.strip()]


def referenced_tables(sql: str) -> set[str]:
    """Table-ish names appearing after FROM or JOIN, lowercased."""
    return {m.group(1).lower() for m in _TABLE_REF.finditer(_skeleton(sql))}


def guard_select(
    sql: str,
    *,
    max_rows: int = 1000,
    allowed_tables: frozenset[str] | None = None,
) -> str:
    """Validate `sql` as a single read-only statement and return it ready to run.

    Raises:
        UnsafeSQLError: if the statement is empty, compound, not a SELECT/WITH,
            contains a destructive verb, or names a table outside the allow-list.
    """
    if not sql or not sql.strip():
        raise UnsafeSQLError("Empty SQL statement.")

    skeleton = _skeleton(sql)
    statements = _split_statements(skeleton)

    if not statements:
        raise UnsafeSQLError("SQL statement contains no executable text.")
    if len(statements) > 1:
        raise UnsafeSQLError(
            f"Only one statement may be executed per call; got {len(statements)}. "
            "Multi-statement SQL is rejected outright."
        )

    words = [w.lower() for w in _WORD.findall(statements[0])]
    if not words:
        raise UnsafeSQLError("SQL statement contains no keywords.")

    if words[0] not in _ALLOWED_HEADS:
        raise UnsafeSQLError(
            f"Only read-only queries are allowed; this statement starts with "
            f"{words[0].upper()!r}. Use SELECT, or WITH ... SELECT."
        )

    found = sorted(_FORBIDDEN.intersection(words))
    if found:
        raise UnsafeSQLError(
            "Read-only queries may not contain "
            + ", ".join(kw.upper() for kw in found)
            + ". If this is a legitimate read, rewrite it without those keywords."
        )

    if allowed_tables is not None:
        referenced = referenced_tables(sql)
        blocked = sorted(referenced - allowed_tables)
        if blocked:
            raise UnsafeSQLError(
                f"Table(s) not in the allow-list: {', '.join(blocked)}. "
                f"Allowed: {', '.join(sorted(allowed_tables)) or '(none)'}."
            )

    return enforce_row_limit(sql, max_rows=max_rows)


def enforce_row_limit(sql: str, *, max_rows: int) -> str:
    """Append a LIMIT when the statement caps no rows of its own.

    A statement that already declares LIMIT / FETCH FIRST / TOP is returned
    untouched; the caller still truncates the result set, so an oversized
    explicit LIMIT cannot flood the response.
    """
    stripped = sql.strip().rstrip(";").rstrip()
    if _HAS_ROW_CAP.search(_skeleton(stripped)):
        return stripped
    return f"{stripped} LIMIT {max_rows}"
