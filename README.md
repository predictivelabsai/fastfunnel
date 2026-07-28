# FastFunnel

FastFunnel is an Apache-2.0, FastHTML-based autonomous marketing cockpit. It is
designed to create, review, distribute, measure, and improve marketing work
while keeping publishing and spend inside explicit company guardrails.

The initial dogfood workspace is [Predictive Labs](https://predictivelabs.ai),
an AI-first platform consultancy. `admin@fastfunnel.app` is seeded as the
approving demo administrator.

![FastFunnel walkthrough](docs/demo/fastfunnel-walkthrough.gif)

## What works now

- Light three-pane FastHTML cockpit with a distinct FastFunnel identity.
- Organization/company/user/membership/invitation persistence.
- Content draft → admin review → bounded autonomous scheduling.
- LangGraph observe → plan → policy-gate workflow.
- Complete vendored Marketing Skills catalog: 49 skills at pinned upstream
  commit `7868cb9251fad80a73d26e488a5ad5f6c4a9f335`.
- Thirty-four registry-driven integration pages including Google, Meta,
  LinkedIn, Instagram/Facebook, X, Buffer, Composio, Arcade, analytics, CRM,
  email, data, and MCP options.
- Honest stubs for Bluesky, Mastodon, and unfinished providers.
- Synthetic/local operation without API credentials.

Live social publishing and ad mutations are intentionally disabled until their
credential, approval, idempotency, and audit adapters are complete.

## Run locally

```bash
cp .env.sample .env
uv sync --extra dev
uv run python -m fastfunnel.app
```

Open <http://127.0.0.1:5005>.

Run the quality gate:

```bash
uv run ruff check .
uv run python -m compileall -q fastfunnel tests
uv run pytest -q
```

Docker:

```bash
docker compose up --build
```

## Demo GIF

With the app running:

```bash
uv run playwright install chromium
uv run python scripts/capture_demo.py
bash scripts/build_demo_gif.sh
```

## Documentation

- [Comprehensive implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Current architecture](docs/ARCHITECTURE.md)
- [Marketing Skills attribution](third_party/marketingskills/UPSTREAM.json)
