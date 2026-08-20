"""The eval harness itself: if the scorer is wrong, every number it reports is."""

from __future__ import annotations

import json

import pytest
from evals.run_eval import (
    CaseResult,
    check_facts,
    evaluate,
    first_expected_rank,
    main,
    source_matches,
    summarise,
)


def result(rank=None, found=(), missed=()):
    return CaseResult(
        id="c",
        question="q",
        expected=["a.md"],
        retrieved=[],
        rank=rank,
        facts_found=list(found),
        facts_missed=list(missed),
    )


class TestSourceMatching:
    def test_the_connector_prefix_is_ignored(self):
        assert source_matches("filesystem:revenue_runbook.md", "revenue_runbook.md")

    def test_a_different_document_does_not_match(self):
        assert not source_matches("filesystem:oncall_runbook.md", "revenue_runbook.md")

    def test_a_partial_name_does_not_match(self):
        # 'runbook.md' must not be credited for 'revenue_runbook.md'.
        assert not source_matches("filesystem:revenue_runbook.md", "runbook.md")

    def test_surrounding_whitespace_is_tolerated(self):
        assert source_matches("filesystem: revenue_runbook.md ", " revenue_runbook.md")


class TestRank:
    def test_first_position_is_rank_one(self):
        assert first_expected_rank(["filesystem:a.md", "filesystem:b.md"], ["a.md"]) == 1

    def test_later_position_is_reported(self):
        assert first_expected_rank(["filesystem:b.md", "filesystem:a.md"], ["a.md"]) == 2

    def test_absent_source_is_none(self):
        assert first_expected_rank(["filesystem:b.md"], ["a.md"]) is None

    def test_any_acceptable_source_counts(self):
        assert first_expected_rank(["filesystem:b.md"], ["a.md", "b.md"]) == 1

    def test_the_earliest_acceptable_source_wins(self):
        retrieved = ["filesystem:c.md", "filesystem:b.md", "filesystem:a.md"]
        assert first_expected_rank(retrieved, ["a.md", "b.md"]) == 2

    def test_empty_retrieval_is_a_miss(self):
        assert first_expected_rank([], ["a.md"]) is None


class TestFactChecking:
    def test_a_present_string_is_found(self):
        found, missed = check_facts("It runs at 02:00 UTC.", ["02:00"])
        assert found == ["02:00"]
        assert missed == []

    def test_an_absent_string_is_missed(self):
        _, missed = check_facts("It runs nightly.", ["02:00"])
        assert missed == ["02:00"]

    def test_matching_is_case_insensitive(self):
        found, _ = check_facts("Set IS_CURRENT = true", ["is_current"])
        assert found == ["is_current"]

    def test_alternatives_count_as_one_fact(self):
        found, missed = check_facts("retries three times", [["three", "3"]])
        assert found == ["three"]
        assert missed == []

    def test_alternatives_missed_only_when_none_match(self):
        _, missed = check_facts("retries a few times", [["three", "3"]])
        assert missed == ["three"]

    def test_no_expectations_yields_nothing(self):
        assert check_facts("anything", []) == ([], [])


class TestMetrics:
    def test_hit_follows_rank(self):
        assert result(rank=2).hit
        assert not result(rank=None).hit

    @pytest.mark.parametrize(("rank", "expected"), [(1, 1.0), (2, 0.5), (4, 0.25), (None, 0.0)])
    def test_reciprocal_rank(self, rank, expected):
        assert result(rank=rank).reciprocal_rank == expected

    def test_groundedness_is_none_when_nothing_was_expected(self):
        assert result(rank=1).groundedness is None

    def test_groundedness_is_the_found_fraction(self):
        assert result(rank=1, found=["a", "b"], missed=["c"]).groundedness == pytest.approx(2 / 3)

    def test_summary_averages_across_cases(self):
        summary = summarise([result(rank=1), result(rank=2), result(rank=None)])
        assert summary["cases"] == 3
        assert summary["hit_rate"] == pytest.approx(2 / 3)
        assert summary["mrr"] == pytest.approx((1.0 + 0.5 + 0.0) / 3)

    def test_groundedness_is_none_when_no_answers_were_scored(self):
        assert summarise([result(rank=1)])["groundedness"] is None


class TestAgainstTheRealGoldenSet:
    """Guards the corpus and the golden set together: either drifting breaks these."""

    def test_every_case_is_well_formed(self, golden):
        for case in golden["cases"]:
            assert case["id"]
            assert case["question"]
            assert case["expect_sources"]

    def test_case_ids_are_unique(self, golden):
        ids = [c["id"] for c in golden["cases"]]
        assert len(ids) == len(set(ids))

    def test_every_expected_source_exists_in_the_corpus(self, golden, repo_root):
        corpus = repo_root / golden["corpus"]
        available = {p.name for p in corpus.rglob("*.md")}
        for case in golden["cases"]:
            for source in case["expect_sources"]:
                assert source in available, f"{case['id']} expects missing {source}"

    def test_retrieval_clears_the_committed_floor(self, golden):
        summary = summarise(evaluate(golden, top_k=4, want_answers=False))
        assert summary["hit_rate"] >= 0.80
        assert summary["mrr"] >= 0.55


class TestCli:
    def test_answers_are_refused_against_the_mock_backend(self, monkeypatch, capsys):
        """Scoring an echo would produce a number that looks like a measurement."""
        monkeypatch.delenv("DA_MODEL_BACKEND", raising=False)
        assert main(["--answers"]) == 2
        assert "refusing" in capsys.readouterr().err

    def test_a_met_threshold_exits_zero(self):
        assert main(["--min-hit-rate", "0.5"]) == 0

    def test_an_unmet_threshold_exits_one(self, capsys):
        assert main(["--min-hit-rate", "0.999"]) == 1
        assert "FAIL" in capsys.readouterr().err

    def test_an_unmeasured_metric_cannot_pass_a_threshold(self, capsys):
        assert main(["--min-groundedness", "0.5"]) == 1
        assert "not measured" in capsys.readouterr().err

    def test_json_output_is_written(self, tmp_path):
        out = tmp_path / "result.json"
        assert main(["--json", str(out)]) == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["summary"]["cases"] > 0
        assert payload["cases"][0]["retrieved"]
