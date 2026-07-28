# FastFunnel Agent Evals

The eval suite exercises the live LangGraph agency using structured cases from
`agent_eval_cases.json`. The initial evaluator is deterministic and checks:

- required proposal types;
- low-risk actions allowed by bounded autonomy;
- high-risk spend actions held for approval;
- expected graph status;
- required and prohibited brand/policy terms.

Run:

```bash
uv run python -m evals.run_eval
uv run python -m evals.run_eval --category policy
uv run python -m evals.run_eval --limit 2
```

Outputs:

- `eval/eval-results.json` — machine-readable case details and assertions.
- `evals/EVAL_REPORT.md` — concise human-readable summary.

Future provider-backed judges may add groundedness, correctness, relevance, and
brand-quality scores. They must be optional and supplement—not replace—the
credential-free policy checks.
