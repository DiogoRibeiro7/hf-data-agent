"""The read-only guard is the only thing standing between caller-supplied SQL and
the warehouse engine, so it gets tested adversarially rather than happy-path."""

from __future__ import annotations

import pytest

from data_agent.datasources.sql_guard import (
    UnsafeSQLError,
    enforce_row_limit,
    guard_select,
    referenced_tables,
)

DESTRUCTIVE = [
    pytest.param("DROP TABLE revenue", id="drop"),
    pytest.param("DELETE FROM revenue", id="delete"),
    pytest.param("INSERT INTO revenue VALUES (1)", id="insert"),
    pytest.param("UPDATE revenue SET revenue_usd = 0", id="update"),
    pytest.param("TRUNCATE TABLE revenue", id="truncate"),
    pytest.param("ALTER TABLE revenue ADD COLUMN x INT", id="alter"),
    pytest.param("CREATE TABLE evil (x INT)", id="create"),
    pytest.param("GRANT ALL ON revenue TO PUBLIC", id="grant"),
    pytest.param("PRAGMA table_info(revenue)", id="pragma"),
    pytest.param("ATTACH DATABASE '/etc/passwd' AS leak", id="attach"),
    pytest.param("VACUUM", id="vacuum"),
    pytest.param("CALL some_procedure()", id="call"),
]

EVASIONS = [
    pytest.param("SELECT 1; DROP TABLE revenue", id="stacked-statements"),
    pytest.param("SELECT 1;DROP TABLE revenue;", id="stacked-no-space"),
    pytest.param("SELECT * FROM revenue -- comment\n; DROP TABLE revenue", id="after-line-comment"),
    pytest.param("SELECT /* DROP */ * FROM revenue; DELETE FROM revenue", id="after-block-comment"),
    pytest.param(
        "WITH x AS (DELETE FROM revenue RETURNING *) SELECT * FROM x",
        id="data-modifying-cte",
    ),
    pytest.param("SELECT * INTO copies FROM revenue", id="select-into"),
    pytest.param("select\n  *\nfrom revenue;\ndrop table revenue", id="multiline-stacked"),
    pytest.param("SeLeCt 1; DrOp TaBlE revenue", id="mixed-case-stacked"),
]


@pytest.mark.parametrize("sql", DESTRUCTIVE)
def test_destructive_statements_are_rejected(sql):
    with pytest.raises(UnsafeSQLError):
        guard_select(sql)


@pytest.mark.parametrize("sql", EVASIONS)
def test_evasion_attempts_are_rejected(sql):
    with pytest.raises(UnsafeSQLError):
        guard_select(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM revenue",
        "select region, sum(revenue_usd) from revenue group by region",
        "WITH totals AS (SELECT region FROM revenue) SELECT * FROM totals",
        "SELECT * FROM revenue ORDER BY month DESC",
        "SELECT * FROM revenue;",  # a single trailing semicolon is fine
        "  \n SELECT 1 \n ",
    ],
)
def test_read_only_queries_are_allowed(sql):
    assert guard_select(sql)


def test_semicolon_inside_a_string_literal_is_not_a_statement_break():
    # A naive split(";") would reject this valid query.
    out = guard_select("SELECT * FROM revenue WHERE note = 'a;b'")
    assert "a;b" in out


def test_keyword_inside_a_string_literal_does_not_trip_the_guard():
    assert guard_select("SELECT * FROM revenue WHERE note = 'please drop table'")


def test_keyword_as_part_of_an_identifier_is_allowed():
    # 'created_at' contains 'create' but is not the CREATE keyword.
    assert guard_select("SELECT created_at, updated_by FROM revenue")


@pytest.mark.parametrize("sql", ["", "   ", "\n\t"])
def test_empty_statements_are_rejected(sql):
    with pytest.raises(UnsafeSQLError, match="Empty"):
        guard_select(sql)


def test_comment_only_statement_is_rejected():
    with pytest.raises(UnsafeSQLError):
        guard_select("-- just a comment")


def test_error_message_names_the_offending_keyword():
    # Single statement, so it reaches the keyword check rather than the
    # multi-statement check, and the message should say what was wrong.
    with pytest.raises(UnsafeSQLError, match="DELETE"):
        guard_select("WITH x AS (DELETE FROM revenue RETURNING *) SELECT * FROM x")


def test_stacked_statements_are_reported_as_such():
    with pytest.raises(UnsafeSQLError, match=r"[Oo]nly one statement"):
        guard_select("SELECT 1; DROP TABLE revenue")


class TestRowLimit:
    def test_limit_is_appended_when_absent(self):
        assert guard_select("SELECT * FROM revenue", max_rows=50).endswith("LIMIT 50")

    def test_existing_limit_is_preserved(self):
        assert guard_select("SELECT * FROM revenue LIMIT 5", max_rows=50).endswith("LIMIT 5")

    def test_fetch_first_counts_as_a_row_cap(self):
        out = enforce_row_limit("SELECT * FROM revenue FETCH FIRST 10 ROWS ONLY", max_rows=50)
        assert "LIMIT" not in out.upper()

    def test_trailing_semicolon_is_stripped_before_appending(self):
        assert guard_select("SELECT * FROM revenue;", max_rows=7) == "SELECT * FROM revenue LIMIT 7"


class TestTableAllowList:
    def test_allowed_table_passes(self):
        assert guard_select("SELECT * FROM revenue", allowed_tables=frozenset({"revenue"}))

    def test_disallowed_table_is_rejected(self):
        with pytest.raises(UnsafeSQLError, match="secrets"):
            guard_select("SELECT * FROM secrets", allowed_tables=frozenset({"revenue"}))

    def test_join_onto_a_disallowed_table_is_rejected(self):
        with pytest.raises(UnsafeSQLError, match="salaries"):
            guard_select(
                "SELECT * FROM revenue JOIN salaries ON 1=1",
                allowed_tables=frozenset({"revenue"}),
            )

    def test_none_means_unrestricted(self):
        assert guard_select("SELECT * FROM anything", allowed_tables=None)

    def test_referenced_tables_finds_from_and_join(self):
        found = referenced_tables("SELECT * FROM a JOIN b ON 1=1 LEFT JOIN c ON 1=1")
        assert found == {"a", "b", "c"}
