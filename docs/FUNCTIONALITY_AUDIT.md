# FastFunnel functionality audit

Last verified: 2026-07-30

This is the browser-level acceptance inventory for the authenticated product.
The audit covers every destination rendered by the left navigation: 16 product
routes and 37 provider-detail routes. A route is only described as functional
when it has a persisted read or write path; provider capability states remain
honest (`connected`, `available`, or `Coming soon`).

## Product routes

| Navigation | Route | Persisted functionality and acceptance check |
|---|---|---|
| Dashboard | `/` | Workspace-scoped KPI evidence, active integrations, action queue, and recent activity. |
| Plan | `/plan` | Live funnel evidence, measured KPIs, model readiness, saved operating plans, and governed plan generation when a model is configured. |
| Agency | `/agency` | Tenant-scoped conversation and plan history. LangChain model execution is configuration-gated and never impersonates a connected model. |
| Ideas & Content | `/content` | Manual drafts and model-assisted drafts persist to the content workflow; revision generation is explicit. |
| Review | `/review` | Exact content approval and payload-bound external action approval. The empty state leads back to content creation. |
| Calendar | `/calendar` | Month navigation, channel/status filters, tenant-timezone display, direct approved scheduling, pipeline scheduling, rescheduling, reversible unscheduling, publication approval requests, and immutable published history. |
| Paid Campaigns | `/campaigns` | Persisted campaigns, performance facts, ingestion status, Google Ads connection state, and policy-governed paid-media controls. |
| Analytics | `/analytics` | Normalized performance summary and daily channel reporting from tenant-scoped facts. |
| Growth dashboard | `/analytics/growth` | Sessions, activation events, attribution comparison, privacy-thresholded geography, demographics, and a semantic or generic lifecycle Sankey fallback. |
| KPI Explorer | `/analytics/explorer` | Metric and dimension controls over normalized facts with tabular and Plotly output. |
| Acquisition Funnel | `/analytics/funnel` | Configurable funnel definitions, ordered cohort counts, conversion/drop-off tables, and a conserved Sankey visualization. |
| Skills | `/skills` | Searchable, editable FastFunnel overlay library. The pinned upstream Marketing Skills snapshot remains immutable. |
| Integrations | `/integrations` | Complete provider catalog with category/status filters and a direct navigation destination. |
| Workspace settings | `/settings` | Workspace metadata, timezone, LangChain provider/model configuration, and encrypted integration-secret entry points. |
| Team & Invites | `/team` | Workspace-scoped membership listing and invitation workflow. |
| Developers | `/developers` | Workspace API-key issuance and revocation without redisplaying secret material. |

## Provider-detail routes

Every row below was opened in the browser and returned an authenticated HTTP
200 response without a console error or failed resource request.

| State | Providers | Behaviour |
|---|---|---|
| Available | Google Ads, HubSpot, Brevo, Google Sheets, PostgreSQL, FastSheets / FastInsights, Composio, Arcade, FastFunnel MCP server | Shows provider-specific credential/configuration input, connection state, supported capabilities, and truthful validation feedback. A provider is not labelled connected until validation succeeds. |
| Coming soon | Meta Ads, LinkedIn Ads, Microsoft Ads, TikTok Ads, GA4, Search Console, Buffer, LinkedIn, Facebook / Instagram, Threads, X, Bluesky, Mastodon, YouTube, Pinterest, Google Business Profile, Salesforce, Stripe, Mailchimp, Resend, WordPress, CSV / Parquet, FastOffice, BigQuery, S3 storage, Webhooks, Generic REST, Connector SDK | Read-only roadmap state. No inactive form or fake successful action is exposed. |

The available-provider detail URLs are:

- `/integrations/google-ads`
- `/integrations/hubspot`
- `/integrations/brevo`
- `/integrations/google-sheets`
- `/integrations/postgres`
- `/integrations/fastsme`
- `/integrations/composio`
- `/integrations/arcade`
- `/integrations/custom-mcp`

The remaining provider IDs are addressable under `/integrations/{provider-id}`
and deliberately show `Coming soon`.

## Cross-cutting acceptance criteria

- Tenant identity is resolved before every authenticated route and all domain
  reads/writes carry the active company ID.
- Sidebar sections independently expand and minimise, persist their state in
  local storage, and offer global `<<` and `>>` controls.
- Calendar times are entered and displayed in the tenant timezone and persisted
  as timezone-aware UTC values.
- Unscheduling is reversible: it moves an item back to `approved`; it does not
  delete the content or its audit history.
- External publication and paid-media mutations are proposed through the action
  service, require exact-payload approval, and remain idempotent/auditable.
- Empty queues offer a relevant next action instead of presenting a blank page.
- Stub integrations are intentionally non-interactive and explicitly labelled
  `Coming soon`.

## Repeatable verification

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run python -m compileall -q fastfunnel tests
```

For browser acceptance, start a disposable seeded database and visit every
sidebar link in an authenticated local session. Exercise the calendar create,
reschedule, unschedule, and re-schedule transitions, then confirm there are no
failed requests or console errors. Store screenshots under `output/playwright/`;
they are test artifacts and must not be committed.
