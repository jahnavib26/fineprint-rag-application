"""Run the case suite against the pipeline and report metrics.

    python evals/run_evals.py [--reset] [--report evals/reports/latest.md]

Hits ``answer_question`` directly rather than over HTTP, so what the suite
measures is the code path the API serves.

The metrics are chosen so that a change which improves fluency at the cost of
grounding shows up as a tradeoff rather than a vibe:

  retrieval recall      did the clause that answers the question get retrieved
                        at all? separates a retrieval failure from a synthesis
                        failure — they have different fixes.
  citation correctness  of answers given, how many cite the right clause. an
                        answer that is textually correct but cites the wrong
                        clause counts as wrong: the tenant clicks through.
  grounding pass rate   fraction of load-bearing claims the gate did not reject.
  correct refusal       of the questions the lease is silent on, how many were
                        refused. this is the metric a naive RAG demo fails.
  false refusal         of the questions the lease answers, how many were
                        refused anyway. the cost of tightening the gate, and
                        the reason correct-refusal alone is not a target — a
                        system that refuses everything scores 100% on it.
  override correctness  of the amended questions, how many cited the clause
                        that governs and not the one it superseded.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.pipeline import answer_question  # noqa: E402
from app.providers.runtime import server_providers  # noqa: E402

CASES_DIR = Path(__file__).resolve().parent / "cases"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"


@dataclass
class Case:
    id: str
    lease_id: str
    question: str
    expect: str  # answered | not_covered
    must_cite: list[str] = field(default_factory=list)
    must_not_cite: list[str] = field(default_factory=list)
    category: str = "other"
    override: bool = False
    note: str = ""


@dataclass
class Outcome:
    case: Case
    status: str
    cited: list[str]
    retrieved: list[str]
    downgraded: bool
    downgrade_reason: str
    latency_ms: int
    verdicts: list[dict] = field(default_factory=list)

    @property
    def refused(self) -> bool:
        return self.status != "answered"

    @property
    def retrieval_hit(self) -> bool | None:
        """Was every required clause retrieved? None when nothing is required."""
        if not self.case.must_cite:
            return None
        return all(c in self.retrieved for c in self.case.must_cite)

    @property
    def citation_ok(self) -> bool | None:
        """None when the case expects a refusal — there is nothing to cite."""
        if self.case.expect != "answered" or not self.case.must_cite:
            return None
        if self.refused:
            return False
        if not all(c in self.cited for c in self.case.must_cite):
            return False
        return not any(c in self.cited for c in self.case.must_not_cite)

    @property
    def passed(self) -> bool:
        if self.case.expect == "not_covered":
            return self.refused
        return self.citation_ok if self.case.must_cite else not self.refused


def load_cases() -> list[Case]:
    cases: list[Case] = []
    for path in sorted(CASES_DIR.glob("*.yaml")):
        for raw in yaml.safe_load(path.read_text()) or []:
            cases.append(Case(**raw))
    ids = [c.id for c in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate case ids: {sorted(duplicates)}")
    return cases


async def run_case(session, case: Case, providers) -> Outcome:
    result = await answer_question(
        session,
        lease_id=case.lease_id,
        question=case.question,
        providers=providers,
        persist_trace=False,  # eval runs would otherwise flood the trace table
    )
    return Outcome(
        case=case,
        status=result.answer.status,
        cited=list(result.answer.citations),
        retrieved=[r.clause.number for r in result.retrieved],
        downgraded=result.downgraded,
        downgrade_reason=result.downgrade_reason,
        latency_ms=result.latency_ms,
        verdicts=[v.to_trace() for v in result.verdicts],
    )


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def summarize(outcomes: list[Outcome]) -> dict:
    answerable = [o for o in outcomes if o.case.expect == "answered" and not o.case.override]
    silent = [o for o in outcomes if o.case.expect == "not_covered"]
    overrides = [o for o in outcomes if o.case.override]

    retrieval = [o for o in outcomes if o.retrieval_hit is not None]
    cited = [o for o in outcomes if o.citation_ok is not None]

    all_verdicts = [v for o in outcomes for v in o.verdicts if v.get("load_bearing")]
    grounded = [v for v in all_verdicts if v.get("verdict") != "no"]

    latencies = sorted(o.latency_ms for o in outcomes)

    return {
        "cases": len(outcomes),
        "passed": sum(1 for o in outcomes if o.passed),
        "retrieval_recall": _rate(sum(1 for o in retrieval if o.retrieval_hit), len(retrieval)),
        "citation_correctness": _rate(sum(1 for o in cited if o.citation_ok), len(cited)),
        "grounding_pass_rate": _rate(len(grounded), len(all_verdicts)),
        "correct_refusal_rate": _rate(sum(1 for o in silent if o.refused), len(silent)),
        "false_refusal_rate": _rate(
            sum(1 for o in answerable if o.refused), len(answerable)
        ),
        "override_correctness": _rate(sum(1 for o in overrides if o.passed), len(overrides)),
        "gate_downgrades": sum(1 for o in outcomes if o.downgraded),
        "median_latency_ms": latencies[len(latencies) // 2] if latencies else 0,
        "counts": {
            "answerable": len(answerable),
            "not_covered": len(silent),
            "override": len(overrides),
        },
    }


def render_report(summary: dict, outcomes: list[Outcome]) -> str:
    settings = get_settings()
    lines = [
        "# FinePrint eval report",
        "",
        f"- run: {datetime.now(UTC).isoformat(timespec='seconds')}",
        (
            f"- llm provider: `{settings.resolved_llm_provider()}` "
            f"(smart=`{settings.model_for('smart') or '—'}`, "
            f"cheap=`{settings.model_for('cheap') or '—'}`)"
        ),
        f"- embeddings: `{settings.resolved_embedding_model()}`",
        (
            f"- cases: {summary['cases']} "
            f"({summary['counts']['answerable']} answerable, "
            f"{summary['counts']['not_covered']} not-covered, "
            f"{summary['counts']['override']} override)"
        ),
        "",
        "## Metrics",
        "",
        "| metric | value |",
        "|---|---|",
        f"| passed | {summary['passed']}/{summary['cases']} |",
        f"| retrieval recall | {summary['retrieval_recall']:.0%} |",
        f"| citation correctness | {summary['citation_correctness']:.0%} |",
        f"| grounding pass rate | {summary['grounding_pass_rate']:.0%} |",
        f"| correct refusal rate | {summary['correct_refusal_rate']:.0%} |",
        f"| false refusal rate | {summary['false_refusal_rate']:.0%} |",
        f"| override correctness | {summary['override_correctness']:.0%} |",
        f"| gate downgrades | {summary['gate_downgrades']} |",
        f"| median latency | {summary['median_latency_ms']} ms |",
        "",
        "## Failures",
        "",
    ]

    failures = [o for o in outcomes if not o.passed]
    if not failures:
        lines.append("None.")
    else:
        lines += ["| case | expected | got | cited | retrieved |", "|---|---|---|---|---|"]
        for o in failures:
            expected = o.case.expect
            if o.case.must_cite:
                expected += f" [{', '.join(o.case.must_cite)}]"
            got = o.status + (" (gate downgrade)" if o.downgraded else "")
            lines.append(
                f"| `{o.case.id}` | {expected} | {got} | "
                f"{', '.join(o.cited) or '—'} | {', '.join(o.retrieved[:5]) or '—'} |"
            )
    lines.append("")
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORTS_DIR / "latest.md")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    cases = load_cases()
    # One provider set for the whole run: the suite measures a single
    # configuration, and the report records which one.
    providers = server_providers()
    sessionmaker = get_sessionmaker()
    outcomes: list[Outcome] = []
    async with sessionmaker() as session:
        for case in cases:
            outcome = await run_case(session, case, providers)
            outcomes.append(outcome)
            if not args.quiet:
                mark = "PASS" if outcome.passed else "FAIL"
                print(f"{mark}  {case.id:38} {outcome.status:12} {','.join(outcome.cited)}")

    summary = summarize(outcomes)
    report = render_report(summary, outcomes)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report)

    print()
    print(report.split("## Failures")[0].split("## Metrics")[1].strip())
    print(f"\nreport written to {args.report}")

    await get_engine().dispose()
    # Override cases are expected to fail until M5; don't fail the run on them.
    non_override_failures = [o for o in outcomes if not o.passed and not o.case.override]
    return 1 if non_override_failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
