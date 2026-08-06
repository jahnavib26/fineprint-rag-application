# Evals

```bash
# populate the database first
backend/.venv/bin/python backend/scripts/smoke_retrieval.py --reset
backend/.venv/bin/python evals/run_evals.py
```

Writes a Markdown report to `evals/reports/` and exits non-zero if any
non-override case fails. Override cases are expected to fail until M5, so they
don't break the run — they're the regression fixture that proves M5 works.

## The cases

35 cases in three files, all with ground truth derived from
`scripts/lease_content.py`, which also generates the PDFs — so expectations are
exact rather than hand-labelled.

| file | n | what it tests |
|---|---|---|
| `answerable.yaml` | 17 | the lease answers it; the right clause must be cited |
| `not_covered.yaml` | 13 | the lease is silent; refusing is the correct answer |
| `overrides.yaml` | 5 | an addendum changed the answer; citing the original is wrong |

The not-covered cases are the most valuable ones in the suite, and several are
deliberately adjacent to a topic the lease *does* cover — maple has pet clauses
but says nothing about pet insurance; birch says who pays for internet but not
who provides it. Retrieval always returns something, so passing requires
distinguishing "related" from "answers the question".

The override cases carry `must_not_cite`. Passing requires citing the amending
clause **and not** the superseded one — otherwise an answer that hedges by
citing both would pass, which in practice means telling a tenant their deposit
is either $2,100 or $3,150.

## Metrics

`retrieval_recall` and `citation_correctness` are reported separately on
purpose: they have different fixes. High recall with low citation correctness
means retrieval is fine and synthesis is choosing badly. Low recall means no
amount of prompt work will help.

`correct_refusal_rate` is never read alone — a system that refuses everything
scores 100%. It's only meaningful against `false_refusal_rate`, which is what
tightening the gate costs.

## Baseline: offline providers (no API keys)

| metric | value |
|---|---|
| passed | 12/35 |
| retrieval recall | 91% |
| citation correctness | 45% |
| grounding pass rate | 100% |
| correct refusal rate | 15% |
| false refusal rate | 6% |
| override correctness | 40% |

Read this as a diagnosis, not a score. **Retrieval recall of 91% is the real
result** — clause-aware chunking finds the right clause almost every time,
including `14(b)` for an Airbnb question that shares no vocabulary with it, and
`2.1.1` three levels deep in the tree.

Everything else is bounded by the offline stand-ins. The extractive draft quotes
whatever ranked first, so it can't refuse; the lexical gate passes verbatim
quotes trivially, so it can't catch a topically-wrong answer. Hence 15% correct
refusal and a grounding pass rate of 100% that means nothing. Those two numbers
measure the placeholders, not the design.

The 40% override correctness is worth reading closely: two of the five pass
without an amendment graph, because the amending clause happened to rank first.
That is the "lucky retrieval" the trace format exists to expose — and the reason
these cases check `must_not_cite` rather than just checking the answer text.

Re-run with a real provider key in `.env` to get numbers that measure the
pipeline instead of its fallbacks.
