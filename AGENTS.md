# Repository Guidelines

## Structure

`fastfunnel/app.py` is the FastHTML entry point. Domain services live in
`fastfunnel/domain/`, registries and provider manifests in
`fastfunnel/integrations/`, autonomous workflows in `fastfunnel/agents/`, and
web components/styles in `fastfunnel/web/`. The pinned upstream Marketing Skills
snapshot is under `third_party/marketingskills/`; do not customize files there.
Put workspace-specific behavior in FastFunnel overlays.

## Commands

- `uv sync --extra dev` installs the environment.
- `uv run python -m fastfunnel.app` starts the cockpit on port 5005.
- `uv run pytest -q` runs tests.
- `uv run ruff check .` checks style.
- `uv run python -m compileall -q fastfunnel tests` checks syntax.

## Safety

External publication and paid-media mutations must flow through domain policy,
approval, idempotency, and audit services. Never call a provider write API
directly from a route or prompt. New integrations must accurately advertise
`stub`, `available`, or `connected`; unfinished behavior must never appear live.
Never commit credentials, database files, generated GIF frames, or `.env`.
