# FastFunnel Development Skills

Operational requirements for every implementation change in this repository.

## Mandatory verification

Always run unit tests after modifying Python, schemas, registries, policies, or
agent behavior:

```bash
uv run ruff check .
uv run python -m compileall -q fastfunnel tests evals
uv run pytest -q
```

Always run a real Playwright MCP/CLI browser test after changing routes, UI,
forms, navigation, CSS, content state transitions, or authentication. Use the
installed Playwright skill wrapper, take a fresh snapshot before using element
references, and verify at least one affected user flow:

```bash
command -v npx
~/.codex/skills/playwright/scripts/playwright_cli.sh open http://127.0.0.1:5005
~/.codex/skills/playwright/scripts/playwright_cli.sh snapshot
```

Store temporary browser artifacts only in `output/playwright/`. Regenerate the
tracked walkthrough GIF when the visible product tour changes:

```bash
uv run python scripts/capture_demo.py
bash scripts/build_demo_gif.sh
```

## Agent evaluations

Run deterministic, credential-free agent evaluations whenever LangGraph nodes,
autonomy policies, tool routing, or proposal formats change:

```bash
uv run python -m evals.run_eval
uv run python -m evals.run_eval --category policy
```

Cases live in `evals/agent_eval_cases.json`; results are written to
`eval/eval-results.json` and `evals/EVAL_REPORT.md`. Future LLM-judge metrics
must remain optional and must not replace deterministic policy assertions.

## External mutations

Publishing and paid-media writes require tenant checks, policy evaluation,
payload-bound approval where applicable, idempotency, provider receipts, and
audit logging. Never call a provider mutation directly from FastHTML routes,
skills, prompts, or unguarded LangGraph nodes.
