"""The example Airflow DAG.

Split deliberately. The *behaviour* — turning a non-zero exit into an exception
so a scheduler sees a failed task — lives in `data_agent.entrypoints.ingest`
and is executed here for real. The DAG file itself cannot be imported without
Airflow installed, so it is checked structurally with the AST.

That is weaker than running it, and the module docstring says so. What these
tests do catch is the class of mistake that would otherwise only surface in
production: a DAG that backfills a rebuild, runs two rebuilds at once, or drags
the whole agent into every scheduler parse.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from data_agent.entrypoints.ingest import run_or_raise

DAG_PATH = Path(__file__).resolve().parent.parent / "airflow" / "dags" / "data_agent_ingest.py"


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(DAG_PATH.read_text(encoding="utf-8"))


def dag_call(tree: ast.Module) -> ast.Call:
    """The single `with DAG(...)` call in the file."""
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "DAG"
    ]
    assert len(calls) == 1, "expected exactly one DAG definition"
    return calls[0]


def keyword(call: ast.Call, name: str) -> ast.expr:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    raise AssertionError(f"DAG(...) has no {name} argument")


class TestFailureSemantics:
    """Executed for real: this is why the logic is not in the DAG file."""

    def test_a_failed_ingest_raises(self, monkeypatch):
        monkeypatch.setattr("data_agent.entrypoints.ingest.main", lambda argv=None: 2)
        with pytest.raises(RuntimeError, match="exit code 2"):
            run_or_raise(["whatever"])

    def test_a_successful_ingest_is_silent(self, monkeypatch):
        monkeypatch.setattr("data_agent.entrypoints.ingest.main", lambda argv=None: 0)
        assert run_or_raise(["whatever"]) is None

    def test_arguments_reach_the_cli(self, monkeypatch):
        seen: list[list[str] | None] = []
        monkeypatch.setattr(
            "data_agent.entrypoints.ingest.main", lambda argv=None: seen.append(argv) or 0
        )
        run_or_raise(["data/seed", "--notion"])
        assert seen == [["data/seed", "--notion"]]


class TestDagFile:
    def test_the_file_exists_and_parses(self, tree):
        assert isinstance(tree, ast.Module)

    def test_exactly_one_dag_is_defined(self, tree):
        assert dag_call(tree)

    def test_backfill_is_disabled(self, tree):
        """Ingestion always rebuilds from the sources as they are now, so
        replaying missed intervals would run the same job repeatedly."""
        assert ast.literal_eval(keyword(dag_call(tree), "catchup")) is False

    def test_only_one_run_at_a_time(self, tree):
        """Two concurrent rebuilds race on one store: one clears it while the
        other writes, and the knowledge base ends up partial."""
        assert ast.literal_eval(keyword(dag_call(tree), "max_active_runs")) == 1

    def test_a_schedule_is_set(self, tree):
        assert ast.literal_eval(keyword(dag_call(tree), "schedule"))

    def test_retries_are_configured(self, tree):
        source = DAG_PATH.read_text(encoding="utf-8")
        assert "retries" in source
        assert "retry_delay" in source

    def test_the_agent_is_not_imported_at_module_scope(self, tree):
        """The scheduler re-parses DAG files constantly. A top-level import of
        the agent would tax every parse for something only the worker needs."""
        top_level = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
        modules = {n.module or "" for n in top_level if isinstance(n, ast.ImportFrom)} | {
            alias.name for n in top_level if isinstance(n, ast.Import) for alias in n.names
        }
        offenders = {m for m in modules if m.startswith("data_agent")}
        assert not offenders, f"imported at module scope: {offenders}"

    def test_the_task_delegates_to_the_tested_entrypoint(self, tree):
        source = DAG_PATH.read_text(encoding="utf-8")
        assert "run_or_raise" in source

    def test_the_caveat_is_stated(self, tree):
        """This DAG has never been parsed by a real scheduler; saying so is part
        of the deliverable, not a nicety."""
        assert "Not run against a real Airflow" in (ast.get_docstring(tree) or "")
