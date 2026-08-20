"""Evaluate the agent against a golden set.

Two tiers, deliberately separated because only one of them is meaningful
offline:

**Retrieval** (default). Deterministic and dependency-free: rebuild the store
from the corpus, ask each golden question, and measure whether the document that
actually answers it comes back in the top k. This runs in CI and gates on
thresholds, because a retrieval regression is silent otherwise — the agent still
produces a confident answer, just from the wrong document.

**Answers** (``--answers``). Runs the full agent, including the tool loop, and
checks whether the expected facts appear. This needs a real model: the `mock`
backend echoes the question, so scoring it would produce a number that looks
like a measurement and is not one. The script refuses rather than pretend.

    python evals/run_eval.py                       # retrieval only
    python evals/run_eval.py --min-hit-rate 0.85   # gate, as CI does
    DA_MODEL_BACKEND=openai_compatible python evals/run_eval.py --answers
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from data_agent.config import Settings
from data_agent.knowledge.ingest import ingest
from data_agent.knowledge.retriever import Retriever
from data_agent.knowledge.sources.filesystem import FilesystemSource
from data_agent.orchestrator.agent import Orchestrator
from data_agent.runtime import Runtime

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GOLDEN = Path(__file__).resolve().parent / "golden.json"


@dataclass
class CaseResult:
    id: str
    question: str
    expected: list[str]
    retrieved: list[str]
    rank: int | None = None
    answer: str | None = None
    facts_found: list[str] = field(default_factory=list)
    facts_missed: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)

    @property
    def hit(self) -> bool:
        return self.rank is not None

    @property
    def reciprocal_rank(self) -> float:
        return 0.0 if self.rank is None else 1.0 / self.rank

    @property
    def groundedness(self) -> float | None:
        total = len(self.facts_found) + len(self.facts_missed)
        return None if total == 0 else len(self.facts_found) / total


def source_matches(retrieved: str, expected: str) -> bool:
    """`filesystem:revenue_runbook.md` matches the golden `revenue_runbook.md`."""
    return retrieved.split(":", 1)[-1].strip() == expected.strip()


def first_expected_rank(retrieved: list[str], expected: list[str]) -> int | None:
    """1-based rank of the first acceptable source, or None if absent."""
    for position, source in enumerate(retrieved, start=1):
        if any(source_matches(source, want) for want in expected):
            return position
    return None


def check_facts(answer: str, wanted: list) -> tuple[list[str], list[str]]:
    """Split expectations into found and missed.

    An entry is either a string (must appear) or a list of alternatives (any one
    of which counts), so "three" and "3" can express the same fact.
    """
    haystack = answer.lower()
    found: list[str] = []
    missed: list[str] = []
    for entry in wanted:
        options = [entry] if isinstance(entry, str) else list(entry)
        label = options[0]
        if any(opt.lower() in haystack for opt in options):
            found.append(label)
        else:
            missed.append(label)
    return found, missed


def build_settings(store_path: Path, top_k: int) -> Settings:
    """Settings for the eval run: a throwaway store, so the developer's own
    data/vector_store.json is never touched."""
    return Settings(vector_store_path=str(store_path), retrieval_top_k=top_k)


async def score_answers(results: list[CaseResult], cases: list[dict], settings: Settings) -> None:
    runtime = Runtime(settings)
    try:
        orchestrator = Orchestrator(runtime)
        for result, case in zip(results, cases, strict=True):
            reply = await orchestrator.answer(case["question"])
            result.answer = reply.answer
            result.tools_used = [step.tool for step in reply.steps]
            result.facts_found, result.facts_missed = check_facts(
                reply.answer, case.get("expect_answer_contains", [])
            )
    finally:
        await runtime.aclose()


def evaluate(golden: dict, top_k: int, want_answers: bool) -> list[CaseResult]:
    cases = golden["cases"]
    corpus = REPO_ROOT / golden.get("corpus", "data/seed")

    with tempfile.TemporaryDirectory() as tmp:
        settings = build_settings(Path(tmp) / "eval_store.json", top_k)
        ingest([FilesystemSource(str(corpus))], settings)
        retriever = Retriever(settings)

        results = []
        for case in cases:
            contexts = retriever.retrieve(case["question"])
            retrieved = [c.source for c in contexts]
            results.append(
                CaseResult(
                    id=case["id"],
                    question=case["question"],
                    expected=case["expect_sources"],
                    retrieved=retrieved,
                    rank=first_expected_rank(retrieved, case["expect_sources"]),
                )
            )

        if want_answers:
            asyncio.run(score_answers(results, cases, settings))

    return results


def summarise(results: list[CaseResult]) -> dict:
    scored = [r.groundedness for r in results if r.groundedness is not None]
    return {
        "cases": len(results),
        "hit_rate": statistics.fmean(1.0 if r.hit else 0.0 for r in results),
        "mrr": statistics.fmean(r.reciprocal_rank for r in results),
        "groundedness": statistics.fmean(scored) if scored else None,
    }


def report(results: list[CaseResult], summary: dict) -> None:
    width = max(len(r.id) for r in results)
    print(f"{'case'.ljust(width)}  rank  retrieved (top-k)")
    print("-" * (width + 40))
    for r in results:
        rank = str(r.rank) if r.rank else "—"
        top = ", ".join(s.split(":", 1)[-1] for s in r.retrieved[:3]) or "(nothing)"
        flag = " " if r.hit else "✗"
        print(f"{flag}{r.id.ljust(width)} {rank.rjust(4)}  {top}")
        if r.facts_missed:
            print(f"{' ' * (width + 8)}missing facts: {', '.join(r.facts_missed)}")

    print()
    print(f"cases        {summary['cases']}")
    print(f"hit rate     {summary['hit_rate']:.3f}")
    print(f"MRR          {summary['mrr']:.3f}")
    if summary["groundedness"] is not None:
        print(f"groundedness {summary['groundedness']:.3f}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument(
        "--answers",
        action="store_true",
        help="also run the agent and score answers (needs a real model backend)",
    )
    parser.add_argument("--min-hit-rate", type=float, default=None)
    parser.add_argument("--min-mrr", type=float, default=None)
    parser.add_argument("--min-groundedness", type=float, default=None)
    parser.add_argument("--json", type=Path, default=None, help="write the full result here")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.answers and Settings().model_backend == "mock":
        print(
            "refusing to score answers against the 'mock' backend: it echoes the "
            "question, so any score would be meaningless. Set DA_MODEL_BACKEND to "
            "transformers, openai_compatible or hf_inference.",
            file=sys.stderr,
        )
        return 2

    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    results = evaluate(golden, args.top_k, args.answers)
    summary = summarise(results)
    report(results, summary)

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "summary": summary,
                    "cases": [
                        {
                            "id": r.id,
                            "question": r.question,
                            "expected": r.expected,
                            "retrieved": r.retrieved,
                            "rank": r.rank,
                            "answer": r.answer,
                            "facts_found": r.facts_found,
                            "facts_missed": r.facts_missed,
                            "tools_used": r.tools_used,
                        }
                        for r in results
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    failures = []
    for name, floor in (
        ("hit_rate", args.min_hit_rate),
        ("mrr", args.min_mrr),
        ("groundedness", args.min_groundedness),
    ):
        value = summary.get(name)
        if floor is None:
            continue
        if value is None:
            flag = "--min-" + name.replace("_", "-")
            failures.append(f"{name} was not measured, so {flag} cannot pass")
        elif value < floor:
            failures.append(f"{name} {value:.3f} is below the required {floor:.3f}")

    if failures:
        print()
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
