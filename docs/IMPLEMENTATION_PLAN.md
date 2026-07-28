# FastFunnel — Product and Implementation Plan

Status: proposed architecture, 2026-07-28
License target: Apache-2.0 (already present)
Primary local benchmark: a production FastHTML marketing cockpit

## 1. Product thesis

FastFunnel is a self-hostable, forkable, AI-operated marketing cockpit built
with Python and FastHTML. It closes the loop between:

1. **Create** — research, ideate, draft, repurpose, and generate campaign assets.
2. **Review** — apply brand, legal, factual, platform, and human approval gates.
3. **Distribute** — schedule and publish organic content and create/manage paid
   campaigns.
4. **Measure** — ingest channel, web, CRM, and revenue data into a governed
   cross-channel model.
5. **Iterate** — diagnose performance, propose experiments, execute approved
   changes, and retain the outcome as organizational memory.

The goal is not just a free dashboard or another agent chat. FastFunnel should
be an open marketing operating system that can run supervised or progressively
autonomous workflows without hiding credentials, data, or business logic in a
proprietary SaaS.

### Product promise

> Connect the business, give the agency a goal and budget, review its plan, and
> let it execute and learn within explicit guardrails.

### Non-goals for the first release

- Claiming feature parity with the full Buffer, Funnel, or Supermetrics web
  products. Initial Buffer parity means the functionality exposed by its public
  developer API, with extensions added incrementally.
- Browser automation as the default for platforms with supported APIs.
- Fully unattended ad spend or public posting on first connection.
- Building hundreds of shallow connectors before the connector SDK and the
  first-party data model are stable.
- Training foundation models.

## 2. Evidence and benchmark review

### 2.1 Primary FastHTML implementation benchmark

Assets to adapt:

- FastHTML + HTMX three-pane cockpit: section navigation, central workspace,
  persistent AI rail, SSE streaming, responsive layout.
- Six-agent taxonomy: content, strategy, social, CRO, SEO, and ads.
- Agent registry and typed tool definitions.
- Synthetic versus actual data modes for credential-free demos.
- Google Ads and Meta Ads direct clients for campaign reads, performance,
  pause/resume, budget updates, and paused-by-default campaign creation.
- LinkedIn Ads reporting client and common performance-row shape.
- Idempotent Google/Meta/LinkedIn sync into Postgres plus run auditing and a
  scheduled GitHub Actions precedent.
- Draft → review/edit → approve/reject → post workflow with immutable action
  history.
- Arcade-based LinkedIn/X publication.
- Marketing skills catalog and product context concept.
- Dashboard, SEO audit, natural-language data chat, and campaign controls.

Items to redesign rather than copy:

- `web/app.py` is a large single-file application; FastFunnel needs bounded
  modules and route packages.
- Direct clients return untyped dictionaries and catch broad exceptions.
- The normalized ad schema is too narrow for attribution, creative analytics,
  dimensions, currencies, account hierarchies, or slowly changing entities.
- The Composio integration is a non-functional stub.
- Arcade is coupled to one account-level user ID.
- LinkedIn is read-only and its hard-coded default API version is stale.
- The agent registry does not provide durable orchestration, retries,
  idempotency, approvals, budgets, or resumability.
- Password authentication and single-tenant assumptions are insufficient for a
  reusable agency product.
- Data-source switching happens globally rather than per workspace/connection.
- Domain-specific tender tables and prompts must not leak into the core.

Recommended extraction method: port behavior and tests deliberately into a new
package layout. Do not copy whole files; retain attribution where source code is
reused and confirm the sister repository's license before doing so.

### 2.2 `mmg/admin-main`: secondary cockpit/data benchmark

Useful patterns:

- Small connector base class, registry, fixture payloads, and offline connector
  tests.
- Long-form normalized marketing fact table.
- SQLite locally and Postgres in production behind one warehouse interface.
- Connector status page with setup instructions.
- Sample data and seeding for demos.
- FastHTML marketing analytics and integrations views.
- Human-gated WordPress → LinkedIn draft pipeline.

Limitations to avoid:

- Delete-and-replace partition writes do not preserve raw history or revisions.
- A single fact table is useful for reporting but insufficient as the canonical
  store.
- Configuration in YAML plus environment variables does not solve multi-user
  OAuth or encrypted secret storage.

### 2.3 Production marketing-site lessons

The repo reinforces production needs that should be first-class in FastFunnel:

- Google Consent Mode v2, Meta Pixel/CAPI, LinkedIn Insight Tag, and server-side
  conversion collection.
- Google/Meta/LinkedIn campaign reporting in one schema.
- Sync audits, failure alerts, and scheduled execution.
- Campaign and UTM taxonomy, FX normalization, and real signup/revenue joins.
- Concrete separation of synthetic demo data from production marketing data.

### 2.4 Product benchmark synthesis

Funnel's strongest concepts to reproduce are:

- Store immutable raw extracts so transformations can be reapplied historically.
- A marketing-aware semantic layer, including channel/campaign mapping, budgets,
  targets, validation, and custom business rules.
- Connector health, schema drift handling, backfills, governed definitions, and
  many destinations.
- An MCP-accessible, contextualized marketing data layer.

Supermetrics' strongest concepts to reproduce are:

- Low-friction source setup and scheduled refreshes.
- Pre-built reporting schemas and cross-source blending.
- Sheets, Excel, BI, warehouse, API, dashboard, AI, and activation destinations.
- Insight agents that turn analysis into recommended or executed action.
- Audience and journey activation back into advertising/engagement tools.

The complete Marketing Skills repository is a built-in, versioned knowledge
pack. It is not a cherry-picked optional afterthought. FastFunnel should:

- Vendor all upstream skill files and references under
  `third_party/marketingskills/`, pinning the exact upstream commit.
- Include the upstream MIT `LICENSE`, copyright notice, source URL, commit, and a
  machine-readable `UPSTREAM.json`.
- Expose every discovered skill in the cockpit from the first usable release,
  even when its executor is initially marked `stub`.
- Load organization-specific context as an overlay; never overwrite upstream
  source files with one customer's brand details.
- Add tests for manifests, references, required inputs, structured outputs, and
  safety policy.
- Allow administrators to enable, disable, fork, or replace every skill.
- Provide an explicit upstream update command that clones to a temporary
  location, shows a reviewable diff, refreshes attribution/version metadata,
  runs the complete skill conformance suite, and never silently updates at
  runtime.

The catalog reviewed on 2026-07-28 contains 49 skills and 248 files:

```text
ab-testing                 ad-creative              ads
ai-seo                     analytics                aso
attribution                churn-prevention         co-marketing
cold-email                 community-marketing      competitor-profiling
competitors                content-strategy         copy-editing
copywriting                cro                      customer-research
directory-submissions      emails                   free-tools
image                      influencer-marketing     launch
lead-magnets               marketing-council        marketing-ideas
marketing-loops            marketing-plan           marketing-psychology
offers                     onboarding               paywalls
popups                     pricing                  product-marketing
programmatic-seo           prospecting              public-relations
referrals                  revops                   sales-enablement
schema                     seo-audit                signup
site-architecture          sms                      social
video
```

## 3. Users, tenancy, and operating modes

### Primary users

- Founder/solo marketer: wants a mostly autonomous agency with simple review.
- In-house team: needs roles, campaigns, approvals, and traceable collaboration.
- Agency: operates many isolated clients, brands, accounts, and reporting views.
- Developer/operator: self-hosts, writes connectors and skills, and changes
  models/providers.
- Analyst: needs governed metrics, exports, notebooks/SQL, and reproducibility.

### Tenancy hierarchy

```text
Installation
└── Organization / agency
    ├── Members, teams, policies, provider settings
    └── Workspace / client brand
        ├── Brand and product context
        ├── Goals, budgets, funnels, audiences
        ├── Connections and ad/social accounts
        ├── Campaigns, content, assets, approvals
        ├── Data model, metrics, experiments
        └── Agent runs, audit logs, costs, memory
```

All persisted business records include `organization_id` and `workspace_id`.
Database policies and application queries must enforce both. A connection may
be shared with selected workspaces but is never global implicitly.

### Autonomy levels

1. **Observe** — read data and draft insights only.
2. **Recommend** — create plans and proposed changes.
3. **Draft** — create content/campaign drafts but cannot schedule or spend.
4. **Supervised execute** — execute each approved action.
5. **Guardrailed autonomy** — execute pre-authorized action classes within
   budget, channel, time, and risk limits.

Default is level 2. Public posting, campaign enablement, audience upload, budget
increase, deletion, and conversion-data transmission each have separate policy
controls. Autonomy is configured per workspace, integration, and action class.

## 4. Core user journeys

### 4.1 Workspace onboarding

1. Create workspace or start with a local single-user workspace.
2. Enter/import product context: product, ICP, positioning, competitors, voice,
   claims, forbidden claims, offers, funnel stages, markets, languages, goals.
3. Connect analytics, ad, social, CMS, CRM, email, and revenue systems.
4. Discover accessible accounts/channels and explicitly bind them.
5. Run connection validation and a small historical sync.
6. Select north-star metric, reporting currency/timezone, attribution model,
   approval policy, and monthly/daily spend limits.
7. Generate the first channel audit and 30-day marketing plan.

### 4.2 Create → review → distribute

```text
Brief/goal
  → research evidence
  → master content/creative concept
  → channel variants + assets
  → automated review gates
  → human review/edit/approval (policy-dependent)
  → schedule/queue/publish
  → delivery receipts and failure recovery
  → post-level performance
```

Every generation stores source evidence, prompt/template version, model,
parameters, cost, output revision, reviewer actions, and destination receipts.

### 4.3 Paid campaign loop

```text
Goal + budget + funnel stage
  → strategy and forecast
  → campaign/ad set/group/creative draft
  → policy and platform validation
  → approval
  → create PAUSED
  → preflight check
  → enable (separate approval)
  → daily monitoring
  → proposed optimization
  → approved/guardrailed action
  → experiment result and learning
```

### 4.4 Weekly autonomous agency review

- Verify data freshness and attribution quality.
- Compare results to goal, budget, baseline, and statistical uncertainty.
- Explain material movements and data caveats.
- Rank opportunities by expected impact, confidence, effort, and risk.
- Create experiments and content/campaign tasks.
- Execute only allowed actions.
- Send a concise report with links to evidence and undo controls.

## 5. Functional scope

### 5.1 Strategy and planning

- Product marketing context with revisions and approval.
- Goal tree: business outcome → marketing objective → KPI → target → deadline.
- Funnel and customer journey designer.
- Audience/persona/segment library.
- Competitor, keyword, messaging, offer, and channel research.
- Campaign calendar, briefs, tasks, owners, dependencies, and budgets.
- Reusable playbooks and skill packs.
- Scenario forecasts with assumptions, ranges, and uncertainty.

### 5.2 Content and creative studio

- Idea/backlog, briefs, documents, variants, media assets, and references.
- Blog, landing page, ad copy, email, social, lead magnet, script, image prompt,
  and video outline creation.
- One master asset repurposed into channel-specific variants.
- Platform length/specification checks.
- Brand voice, factuality/citation, plagiarism, claim, accessibility, policy,
  UTM, SEO, and link checks.
- Version comparison, inline edit, comments, approval, rejection, and requested
  changes.
- Optional image/video generation provider adapters.
- Asset library backed by local filesystem or S3-compatible object storage.

### 5.3 Buffer public-API parity

Implement Buffer-facing behavior as provider-neutral domain services:

| Buffer API capability | FastFunnel domain capability | Initial acceptance |
|---|---|---|
| Organizations | organizations/workspaces | list and select tenant |
| Connected channels | publishing connections/channels | discover, filter, status |
| Ideas | content ideas/backlog | create/list/update/archive |
| Posts | channel-specific publication variants | draft/list/filter/status |
| `addToQueue` | queue slot scheduling | resolve next available slot |
| scheduled time | explicit-time scheduling | timezone/DST safe |
| send now | immediate publication | approval + idempotent dispatch |
| text posts | text publication | all supported providers |
| image posts/assets | media attachment pipeline | upload, validate, publish |
| channel metadata | typed platform options | platform schema validation |
| delete post | cancel/delete scheduled post | policy gate + audit |
| sent/scheduled/draft filters | publication state machine | cursor pagination |
| post metrics | normalized post analytics | preserve raw metrics too |
| API key | personal access token | hashed, scoped, revocable |
| OAuth app client | third-party apps | OAuth 2.1 + PKCE |
| GraphQL endpoint | stable external API | phase after domain service |
| pagination | cursor pagination | deterministic ordering |
| rate-limit headers/errors | quotas | per token/org + retry hints |

Supported publishing targets should aim for the platforms listed by Buffer's
current public API: Instagram, Threads, LinkedIn, X, Facebook, Google Business
Profiles, Mastodon, YouTube, Pinterest, and Bluesky. Phase 1 proves LinkedIn and
one open protocol target (Mastodon or Bluesky); breadth follows the adapter
contract and conformance suite.

Network-specific options should cover threads, first comments, Instagram
post/story/reel types and user tags, Pinterest boards, video metadata, alt text,
and platform-specific link/media constraints as their connectors are added.

Do not clone Buffer's private UI, branding, or undocumented behavior. Build
interoperable product behavior from public documentation and independent code.

### 5.4 Distribution operations

- Visual calendar, queue, list, failed-delivery, and content-gap views.
- Per-channel schedules, timezone, blackout windows, minimum spacing, and
  evergreen recycling policy.
- Bulk actions with preview and approval.
- Idempotent delivery with provider request IDs.
- Retry only safe/retryable failures; otherwise enter a dead-letter queue.
- Reconciliation job to retrieve provider state and avoid duplicate posts.
- Optional Buffer connector so teams can distribute through an existing Buffer
  account while adopting FastFunnel.

### 5.5 Paid advertising

Minimum direct API capability for Google Ads, Meta Ads, and LinkedIn Ads:

- OAuth/app onboarding, account discovery, and permission checks.
- Account/campaign/ad-group or ad-set/ad/creative inventory.
- Daily and intraday performance extracts with raw payload retention.
- Campaign creation as draft/paused.
- Budget, status, schedule, targeting, creative, and URL/UTM management.
- Conversion action/rule discovery and health.
- Search terms/keywords for Google; audience and placement dimensions where
  platforms permit; demographic/creative breakdowns with privacy thresholds.
- Lead form and lead ingestion where authorized.
- Offline/server-side conversion upload with consent and deduplication.
- Audience activation only under explicit high-risk policy.
- Change history, external actor detection, and reconciliation.

Provider-specific notes:

- **Google Ads:** official `google-ads` client, GAQL, developer-token access
  levels, manager/customer hierarchy, partial failure support, request IDs, API
  version upgrade tests, conversion uploads, and paused-by-default mutations.
- **Meta Ads:** official Business SDK/Graph API, system-user or OAuth tokens,
  Business/ad-account discovery, Insights async jobs for large reports, action
  attribution windows, CAPI deduplication, token diagnostics, and version pinning.
- **LinkedIn Ads:** versioned REST API, vetted Advertising API access, account →
  campaign group → campaign → creative hierarchy, Ad Analytics pivots,
  conversions/leads, development versus standard tier constraints, and a
  scheduled monthly-version compatibility review.

No optimization agent may:

- Enable a newly created campaign automatically by default.
- Increase a daily budget beyond both absolute and percentage limits.
- Change billing, add admins, accept legal terms, or create platform accounts.
- Upload customer lists without explicit workspace policy and consent basis.

### 5.6 Analytics, attribution, and intelligence

Sources in priority order:

1. Google Ads, Meta Ads, LinkedIn Ads.
2. GA4 and Google Search Console.
3. Publishing/post metrics.
4. CRM and revenue: generic webhook/CSV plus HubSpot, Salesforce, Stripe.
5. Email: Mailchimp/Resend and an adapter contract.
6. Additional ads: Microsoft, TikTok.

Canonical storage layers:

```text
API/MCP/webhook/file
  → immutable raw objects
  → staged provider tables
  → canonical entities and metric observations
  → semantic definitions and attribution models
  → aggregates/materialized views
  → dashboards, reports, agents, API/MCP, exports
```

The canonical model includes:

- organizations, workspaces, people, roles;
- providers, connections, external accounts, sync cursors, sync runs;
- campaigns, campaign groups, ad groups/sets, ads, creatives, audiences;
- content items, variants, assets, channels, publications, delivery attempts;
- web events, conversions, leads, opportunities, customers, revenue;
- metric definitions, observations, dimensions, currencies, FX rates;
- goals, budgets, forecasts, experiments, variants, decisions;
- agent runs, steps, tool calls, approvals, policies, audit events, model costs.

Raw data must remain replayable. Canonical facts use stable internal IDs plus
provider IDs. Metrics carry provider, attribution window/model, timezone,
currency, ingestion time, event date, and definition version. Avoid pretending
that similarly named conversion metrics are equivalent.

Analytics UX:

- Executive scorecard and goal pacing.
- Cross-channel spend, reach, traffic, conversions, CAC/CPA, revenue, and ROAS.
- Campaign, creative, audience, content, and landing-page drilldowns.
- Funnel/journey visualization and cohort analysis.
- Data freshness, completeness, reconciliation, and schema-drift views.
- Anomaly/change-point alerts with evidence.
- Natural-language analysis that displays generated SQL, definition versions,
  date filters, and source links.
- Saved views, scheduled reports, CSV/Parquet/Sheets/warehouse export.
- First-touch, last-touch, linear, position-based, and data-driven/experimental
  models clearly separated from platform-reported attribution.

### 5.7 Experimentation and learning

- Hypothesis, metric, population, variants, guardrails, start/stop rule.
- A/B tests for content, landing pages, offers, and creatives.
- Pre-period baseline and minimum detectable effect support.
- Do not declare winners from raw uplift alone; show uncertainty/sample caveats.
- Record decisions and subsequent outcomes.
- Feed validated learnings into workspace memory; do not silently rewrite brand
  or strategy context from a single result.

## 6. Integration architecture

### 6.1 Capability-based adapter contract

Avoid a single giant connector interface. An adapter declares granular
capabilities:

```python
class Capability(str, Enum):
    ACCOUNTS_READ = "accounts.read"
    CAMPAIGNS_READ = "campaigns.read"
    CAMPAIGNS_WRITE = "campaigns.write"
    PERFORMANCE_READ = "performance.read"
    CONTENT_PUBLISH = "content.publish"
    CONTENT_METRICS_READ = "content.metrics.read"
    CONVERSIONS_WRITE = "conversions.write"
    AUDIENCES_WRITE = "audiences.write"
```

Each tool resolves through an `IntegrationRouter`:

1. Check workspace policy and requested capability.
2. Prefer the workspace's configured provider route: direct, Composio, Arcade,
   Buffer, or another MCP server.
3. Validate typed input against FastFunnel's canonical command.
4. Convert it to the provider request.
5. Attach idempotency key, actor, tenant, approval, correlation, and run IDs.
6. Execute and store redacted request metadata, response, receipt, and audit.
7. Normalize output to a typed domain result.

The same domain action can therefore use a direct API in one workspace and
Composio/Arcade in another without changing the agent or UI.

### 6.2 Direct API adapters

Direct adapters are the reference path for the minimum Google/Meta/LinkedIn
functionality. They deliver maximum transparency, bulk extraction efficiency,
and self-hosting. Each has:

- Pydantic request/result models.
- Version declaration and support window.
- OAuth scopes and setup metadata.
- Rate-limit and retry classifier.
- Incremental sync cursor/backfill behavior.
- Raw schema version and normalizer.
- Dry-run and validation methods for mutations.
- Contract fixtures with redacted real payload shapes.
- Conformance tests for each advertised capability.

### 6.3 Composio sessions and MCP

Use current Composio sessions, not its deprecated standalone MCP-server API.
Create one session per FastFunnel user/workspace context and request its hosted
MCP endpoint only when MCP transport is desired.

Requirements:

- Map FastFunnel user/workspace IDs to Composio user IDs without exposing email
  addresses unnecessarily.
- Store connected-account references, never Composio tokens, in ordinary tables.
- Allowlist toolkits and tools per workspace; do not expose 1,000+ tools to the
  model.
- Cache tool discovery with a short versioned TTL.
- Translate discovered tools into FastFunnel capabilities.
- Wrap every mutation with the same approval and audit interceptor as direct APIs.
- Pin tool versions when possible and detect schema changes before activation.
- Implement connection challenge UX and callback state/nonce validation.
- First validate LinkedIn Ads (currently broad toolkit coverage), then inventory
  the current Google Ads and Meta Ads toolkit capabilities against direct clients.

Composio is an optional execution/auth provider, not a required control plane.
The application must remain functional with direct connectors only.

### 6.4 Arcade MCP and hosted tools

Use Arcade for user-authorized social tools and as an optional secure MCP
gateway. Arcade currently exposes an optimized LinkedIn text-post tool and
supports custom/self-hosted tools; its built-in LinkedIn surface is not Buffer
parity by itself.

Requirements:

- Production user identity comes from FastFunnel's OIDC subject mapping, not one
  global `ARCADE_USER_ID`.
- Prefer a narrowly configured gateway per environment/use case.
- Use custom Arcade auth providers so consent displays the self-hoster's app.
- Treat authorization challenges as resumable workflow states.
- Add custom Arcade tools only where its runtime/auth materially helps.
- Keep content/media scheduling state inside FastFunnel; provider tools perform
  the final external action.
- Never let Arcade and a direct adapter race to publish the same publication;
  the dispatcher owns a single idempotency lease.

### 6.5 FastFunnel MCP server

Expose a first-party MCP server for other agents:

- Resources: workspace context, metric catalog, saved reports, content/calendar,
  campaign summaries, experiment results.
- Read tools: query governed metrics, inspect content/campaign state, connector
  health, and retrieve evidence.
- Write tools: create briefs/drafts/tasks and propose actions.
- High-risk tools: publish, change budget/status, upload conversion/audience;
  always policy-gated with asynchronous approval support.
- Prompts: weekly review, campaign brief, content repurpose, anomaly diagnosis.

Never expose raw credentials, unbounded SQL, arbitrary HTTP fetch, or unrestricted
provider tools. Defend against prompt injection in external content by labeling
untrusted data and preventing it from altering tool policy.

## 7. Application architecture

### Recommended stack

- Python 3.12+, `uv`, `pyproject.toml`, locked dependencies.
- FastHTML + HTMX + small Alpine-free vanilla JavaScript where unavoidable.
- Pydantic v2 domain contracts.
- SQLAlchemy 2 + Alembic.
- Postgres production; SQLite supported for a local demo subset.
- Redis optional for cache, rate limits, and queue coordination.
- Durable job runner: start with Postgres-backed worker tables and `FOR UPDATE
  SKIP LOCKED`; keep an interface suitable for Temporal later.
- Object storage: local path or S3-compatible provider.
- Plotly initially for charts, with accessible tabular fallbacks.
- OpenTelemetry traces/metrics/logs and structured JSON logging.
- Model gateway supporting OpenAI-compatible endpoints plus explicit provider
  adapters; no hard dependency on one LLM vendor.

### Package layout

```text
fastfunnel/
  app.py
  config.py
  web/
    routes/
    components/
    layouts/
    auth/
    static/
  domain/
    organizations/
    strategy/
    content/
    publishing/
    advertising/
    analytics/
    experiments/
    approvals/
  agents/
    orchestrator.py
    skills/
    policies/
    memory/
  integrations/
    base.py
    router.py
    direct/
      google_ads/
      meta_ads/
      linkedin_ads/
      ga4/
      search_console/
    composio/
    arcade/
    buffer/
    mcp/
  data/
    raw/
    staging/
    canonical/
    semantic/
    exports/
  jobs/
    engine.py
    sync.py
    publish.py
    reconcile.py
    optimize.py
  api/
    graphql/
    rest/
    mcp/
  models/
  migrations/
  observability/
tests/
  unit/
  contract/
  integration/
  e2e/
  fixtures/
docs/
scripts/
```

### FastHTML page map

- `/` — goal pacing, alerts, active work, agent summary.
- `/plan` — strategy, goals, budgets, calendar.
- `/content` — ideas, briefs, drafts, variants, assets.
- `/review` — approval inbox and side-by-side revision editor.
- `/calendar` — queue/schedule and delivery state.
- `/campaigns` — paid campaign overview and management.
- `/analytics` — cross-channel scorecard and drilldowns.
- `/funnel` — journeys, attribution, cohorts.
- `/experiments` — hypotheses, tests, learnings.
- `/agency` — autonomous run history, proposals, policy exceptions.
- `/skills` — all 49 bundled Marketing Skills, grouped by job, with
  ready/stub/disabled/update-available state, source/version, test status, and
  configure/run actions.
- `/integrations` — complete connection catalog, capabilities, health, setup,
  and provider-route selection.
- `/data` — freshness, definitions, lineage, exports, SQL.
- `/settings` — workspace, team, brand, policies, models, secrets.

Use HTMX partial endpoints for tables/forms/panels, server-sent events for long
agent/job progress, signed cursor pagination, progressive enhancement, keyboard
navigation, reduced motion, and WCAG 2.2 AA targets.

### Left-sidebar information architecture

The left sidebar must make scope visible early without presenting unfinished
work as live. Use collapsible groups with counts and status dots:

```text
OVERVIEW
  Dashboard
  Plan
  Agency

CREATE & SHIP
  Ideas & Content
  Review
  Calendar
  Assets

ACQUISITION
  Paid Campaigns
  SEO & AEO
  Email & Lifecycle
  Landing Pages & CRO

MEASURE
  Analytics
  Funnel & Attribution
  Experiments
  Data Quality

SKILLS (49)
  Strategy & research
  Content & creative
  Acquisition
  Conversion & lifecycle
  Measurement
  All skills

INTEGRATIONS
  Overview
  Advertising
    Google Ads
    Meta Ads
    LinkedIn Ads
    Microsoft Ads
    TikTok Ads
  Analytics & search
    Google Analytics 4
    Google Search Console
  Social publishing
    Buffer
    LinkedIn
    Facebook / Instagram
    Threads
    X
    Bluesky
    Mastodon
    YouTube
    Pinterest
    Google Business Profile
  CRM & revenue
    HubSpot
    Salesforce
    Stripe
  Email & CMS
    Mailchimp
    Resend
    WordPress
  Data & destinations
    CSV / Parquet
    Google Sheets
    Postgres
    BigQuery
    S3-compatible storage
    Webhooks
  Agent connection providers
    Composio
    Arcade
    Custom MCP server
  Developer
    Generic REST connector
    Connector SDK

SETTINGS
  Workspace & brand
  Team & approvals
  Models & costs
  Security & audit
```

Every listed integration has a route and detail page from Phase 1. A stub page
must still be useful: show planned capabilities, supported provider routes
(`direct`, `composio`, `arcade`, `buffer`, `custom_mcp`), required credentials
and scopes, implementation milestone, documentation links, and a disabled
connection button labeled `Not implemented`. Status values are strictly:
`available`, `connected`, `degraded`, `not configured`, `stub`, or `disabled`.
The catalog is registry-driven so adding a manifest automatically adds the
sidebar option, overview card, route, setup checklist, and tests.

## 8. Agent system

### Agent roles

- Marketing director: converts business goals into an operating plan.
- Research: market, customer, competitor, keyword, and evidence gathering.
- Content strategist/creator: briefs, drafts, variants, repurposing.
- Reviewer: brand, factual, platform, policy, legal, accessibility checks.
- Distributor: queueing, publication, and delivery reconciliation.
- Paid media: campaign structure, creative, targeting, pacing, optimization.
- Analyst: metric definition, diagnosis, forecasting, attribution, reporting.
- Experimenter: hypotheses, test design, stopping rules, learning.

These are logical roles over one durable orchestrator, not unconstrained agents
chatting with one another. Each run has a typed goal, inputs, allowed tools,
time/token/money budgets, state, outputs, evidence, and terminal conditions.

### Skill execution

Skill packs are data/configuration with executable validators:

- Manifest: ID, version, source/license, description, risks, required context,
  tools, input/output schema.
- Instructions and references.
- Optional deterministic preprocessing/postprocessing.
- Evaluation fixtures and quality rubric.

All 49 Marketing Skills are bundled and discoverable. Implementation status is
per skill:

- `ready`: adapted executor, input/output schema, evaluations, and policy tests.
- `prompt-only`: upstream instructions/references load and run through the
  generic skill executor, but no specialized deterministic tools exist.
- `stub`: visible manifest and planned contract, not executable.
- `disabled`: administrator policy prevents use.

The generic prompt-only executor gives every safe textual skill a useful initial
path; skills that imply external publication, spend, scraping, form submission,
or other side effects remain stubs until they use governed FastFunnel tools.
Upstream sync remains an explicit diff/review/upgrade operation.

### Memory

- Canonical workspace context: human-approved, versioned.
- Episodic run memory: immutable run summaries and evidence.
- Learnings: experiment- or review-backed statements with confidence and expiry.
- Retrieval index: optional pgvector, always scoped by workspace and document
  access.

Model output is not memory merely because it was generated.

## 9. Security, privacy, and governance

### Authentication and authorization

- Local single-user auth for development.
- OIDC for production; optional passkeys later.
- Organization roles: owner, admin, strategist, creator, reviewer, analyst,
  operator, viewer.
- Attribute checks for workspace, connection, action class, spend, and data type.
- Short-lived sessions, CSRF protection, secure cookies, login throttling.
- Scoped personal access tokens and OAuth clients for the external API.

### Secrets

- Envelope-encrypted secrets using a pluggable KMS; development may use a local
  master key outside the database.
- Separate metadata from encrypted credential payloads.
- Redact secrets/tokens/PII from logs, traces, prompts, exception reports, and
  raw API payload previews.
- Rotation, revocation, expiry alerts, and least-privilege scope display.
- Self-hosters may choose direct secrets or delegated Composio/Arcade auth.

### High-risk action controls

- Policy evaluation occurs before tool selection and immediately before execution.
- Approval records bind exact normalized action, payload hash, actor, expiry, and
  material constraints; changed payloads require reapproval.
- Budget changes show old/new values, currency, percentage, projected monthly
  effect, and rollback.
- Destructive actions use soft delete where possible.
- Append-only tamper-evident audit chain for external mutations.
- Kill switch per workspace and globally; revoke queued autonomous mutations.
- Reconciliation detects external/manual changes.

### Privacy and compliance

- Data minimization and configurable retention per raw/canonical data class.
- GDPR export/delete workflows and data-processing inventory.
- Consent state and lawful-basis metadata for conversion and audience activation.
- Hash user identifiers immediately before provider transmission; avoid storing
  unnecessary plaintext.
- Respect provider data-storage, deletion, display, and API terms.
- Region/timezone/currency-aware handling.
- Open-source threat model and security policy before public beta.

## 10. Reliability and data operations

- Idempotency keys for all sync partitions, publications, conversions, and ad
  mutations.
- Exponential backoff with jitter only for classified retryable errors.
- Rate-limit budget shared across workers per provider account.
- Circuit breaker and pause on authentication/policy/schema failures.
- Dead-letter queue with replay after operator review.
- Sync watermarks with overlap windows for late attribution updates.
- Scheduled recent-window re-pulls plus explicit historical backfills.
- Schema drift detector that quarantines incompatible payloads without losing them.
- Provider/canonical reconciliation totals and sampled entity comparison.
- Data-quality checks: uniqueness, referential integrity, ranges, freshness,
  completeness, currency, timezone, and metric invariants.
- Backups, point-in-time recovery guidance, migration rollback/forward strategy.
- SLOs for API, sync freshness, job success, and publication delivery.

Initial SLO targets:

- 99.5% monthly cockpit availability for maintained deployment profile.
- 95% of daily source partitions fresh within 6 hours of schedule.
- 99.9% avoidance of duplicate external publications.
- 100% external mutations represented in the audit log.
- Recovery point objective 24 hours for community default, configurable lower.

## 11. Testing and release gates

### Test layers

- Unit: domain rules, metric math, policy, scheduling/DST, normalizers.
- Golden fixture: redacted provider payload → canonical records.
- Contract: adapter capabilities and error classification.
- Integration: sandbox/test accounts and ephemeral Postgres.
- End-to-end: onboarding, create/review/schedule, ad draft, sync, dashboard.
- Migration: upgrade from each supported release.
- Security: tenant isolation, CSRF, SSRF, secret redaction, prompt injection,
  approval tampering, OAuth state/PKCE.
- Load: large backfills, calendar pagination, agent/job concurrency.
- Evaluation: factuality, brand adherence, action correctness, tool selection,
  and refusal on prohibited actions.

Every external mutation test defaults to dry-run/sandbox. Live smoke tests use
dedicated test accounts and explicit CI secrets; they are never run for forks by
default.

### Definition of done for a connector

- Setup docs and scopes.
- Account discovery and health check.
- Incremental and backfill sync.
- Raw capture and canonical normalization.
- Rate limiting, retries, pagination, and token refresh.
- Typed errors with actionable UI.
- Fixture, contract, integration, and drift tests.
- Observability dashboard and freshness alert.
- Disconnect/revoke behavior.
- Capability and risk declaration.

## 12. Delivery roadmap

Assume two experienced full-time engineers plus part-time design/product. With
one engineer, preserve phase order and roughly double elapsed time. Do not
parallelize connector breadth until the contract and canonical model pass Phase
1 gates.

### Phase 0 — Decisions and foundation (week 1)

- Resolve the open product questions in section 15.
- Add `AGENTS.md`, contribution/security/governance docs, `pyproject.toml`, CI,
  pre-commit/lint/type/test tooling, and architecture decision records.
- Create FastHTML shell, design tokens, responsive navigation, local auth,
  Postgres/SQLite profiles, migrations, and synthetic seed.
- Establish provider-independent IDs, tenant scoping, audit event envelope, and
  typed result/error conventions.
- Vendor the complete Marketing Skills snapshot, license and commit metadata;
  generate and validate all 49 manifests.
- Add the registry-driven Integrations catalog and every planned stub manifest.

Exit: one-command local launch, tests/CI green, demo workspace renders, no
credentials required; all skills and integrations are discoverable with honest
status labels.

### Phase 1 — Thin closed loop from the FastHTML benchmark (weeks 2–4)

- Port/adapt cockpit layout and product-context onboarding.
- Implement content idea → draft → automated checks → review/edit/approve.
- Implement publication state machine, queue, calendar, and synthetic connector.
- Arcade LinkedIn text-post adapter and direct/Arcade route selection.
- Google/Meta/LinkedIn reporting adapters using redacted fixtures.
- Canonical raw/staging/fact pipeline, sync runs, freshness UI.
- Executive/campaign/content analytics on synthetic data.
- Durable worker and SSE progress.
- Complete sidebar and detail routes for every skill and integration manifest.
- Generic prompt-only execution for safe textual Marketing Skills; side-effecting
  skills remain policy-aware stubs until their tool contracts exist.

Exit: a fork can demo create/review/schedule/measure end-to-end; live LinkedIn
posting is optional and approval-gated; all three ad sources pass fixture
conformance.

### Phase 2 — Direct paid-media production slice (weeks 5–8)

- Production OAuth/credential flows and account binding.
- Google and Meta direct campaign inventory, metrics, paused creation,
  pause/resume, and budget changes.
- LinkedIn current-version reporting, then supported write capabilities allowed
  by the approved access tier.
- Policy engine, payload-bound approvals, idempotency, audit, rollback proposals.
- Scheduled incremental sync, overlap re-pulls, backfill, retry/DLQ, alerts.
- FX, timezone, attribution-window metadata, taxonomy, UTM builder.
- GA4 and Search Console.

Exit: one real workspace operates daily reporting and supervised paid actions
for Google/Meta; LinkedIn scope is clearly reported from actual API entitlements.

### Phase 3 — Buffer API parity core and integration providers (weeks 9–12)

- Ideas, organizations/workspaces, channels, posts, queue, explicit schedule,
  send-now, deletion/cancellation, assets, pagination, filters, metrics.
- Stable external API: use GraphQL if Buffer client compatibility is strategic;
  otherwise start REST/OpenAPI and add GraphQL without coupling domain services.
- Personal tokens, OAuth 2.1 PKCE clients, quotas and rate-limit headers.
- Buffer connector, Composio sessions/MCP, Arcade gateway/user-source support.
- Add Bluesky or Mastodon as the second proven publishing provider.
- Provider conformance harness and capability matrix UI.

Exit: all rows in the Buffer parity matrix have automated acceptance tests for
at least the synthetic provider and applicable live adapters.

### Phase 4 — Autonomous agency MVP (weeks 13–16)

- Durable weekly review and anomaly workflows.
- Strategy, research, creator, reviewer, paid-media, analyst, experiment roles.
- Versioned Marketing Skills imports and workspace customization overlay.
- Goal/budget pacing, recommendations, ranked experiments, action proposals.
- Guardrailed autonomy for low-risk scheduling and bounded campaign changes.
- Run replay, cost/token budgets, evidence, and evaluation dashboard.
- First-party FastFunnel MCP server.

Exit: the agency completes a weekly cycle, explains every proposal from governed
data, and executes only pre-authorized actions.

### Phase 5 — Attribution, activation, and agency operations (weeks 17–22)

- CRM/revenue generic ingestion, Stripe, and first CRM connector.
- Conversion uploads/CAPI with consent and deduplication.
- Funnel, cohorts, multi-model attribution, and experiment measurement.
- Audience activation behind high-risk policy.
- Multi-client agency views, templates, shared-but-isolated connections, scheduled
  client reports, white-label theme primitives.
- Sheets/Parquet/S3/Postgres/BigQuery exports.

Exit: demonstrate spend → interaction → lead/customer/revenue and safe feedback
to at least one advertising platform.

### Phase 6 — Industrial hardening and 1.0 (weeks 23–28)

- SLO dashboards, backup/restore drills, load/chaos tests, upgrade tests.
- Threat model, third-party security review, dependency/SBOM/signing pipeline.
- Accessibility audit and localization foundation.
- Connector certification guide and plugin/skill SDK.
- Helm/Docker Compose deployment profiles and documented scaling.
- Public demo, contributor docs, release governance, support policy.

Exit: reproducible 1.0 release, supported upgrade path, security response process,
and evidence that tenant isolation and mutation controls withstand review.

### Post-1.0 connector sequence

1. Instagram/Facebook Pages, X, Threads.
2. YouTube, Pinterest, Google Business Profile.
3. Microsoft Ads, TikTok Ads.
4. HubSpot/Salesforce, Mailchimp, CMS adapters.
5. Additional warehouses/BI and community connectors.

Prioritize usage evidence, API feasibility, and maintainers—not connector count.

## 13. Workstreams and initial epics

### Platform

- PLAT-001 repository/tooling/CI
- PLAT-002 tenant/auth/RBAC
- PLAT-003 encrypted connections
- PLAT-004 durable jobs
- PLAT-005 policy/approval/audit
- PLAT-006 observability and admin

### Content/distribution

- CONT-001 product/brand context
- CONT-002 ideas/briefs/content revisions
- CONT-003 automated review gates
- PUB-001 channels/calendar/queue
- PUB-002 dispatcher/retry/reconciliation
- PUB-003 Buffer parity API

### Advertising/data

- ADS-001 capability contracts
- ADS-002 Google direct
- ADS-003 Meta direct
- ADS-004 LinkedIn direct
- DATA-001 raw/staging/canonical/semantic layers
- DATA-002 GA4/GSC
- DATA-003 attribution/revenue
- DATA-004 exports

### AI/automation

- AI-001 model gateway and structured generation
- AI-002 skill packs and upstream management
- AI-003 durable agency workflows
- AI-004 memory/evidence/evaluations
- AI-005 FastFunnel MCP

### Provider bridges

- BRIDGE-001 Composio sessions/MCP
- BRIDGE-002 Arcade user auth/gateway
- BRIDGE-003 Buffer

## 14. Demo, screenshots, and GIFs

Follow the FastXXX convention:

```text
docs/demo/
  frames/
    01-dashboard.png
    02-plan.png
    03-content-draft.png
    04-review.png
    05-calendar.png
    06-campaigns.png
    07-analytics.png
    08-agency-run.png
  fastfunnel-walkthrough.gif
scripts/
  capture_demo.py
  build_demo_gif.sh
```

`capture_demo.py` should:

- Seed a deterministic synthetic workspace.
- Start from a fixed viewport, timezone, locale, reduced-motion mode, and clock.
- Use Playwright to capture both light and dark tours if both are supported.
- Mask unstable timestamps/IDs and wait for fonts/charts.
- Capture the complete closed loop, not a set of unrelated pages.

`build_demo_gif.sh` should adapt the common sister-repo script:

- ImageMagick `convert`, fallback to `ffmpeg`.
- Configurable delay and width.
- Optimize output and fail if frames are missing.
- Produce `docs/demo/fastfunnel-walkthrough.gif`.

Also generate two focused GIFs after the relevant milestones:

- `fastfunnel-content-loop.gif`: create → review → schedule.
- `fastfunnel-agency-loop.gif`: diagnose → propose → approve → measure.

Add a CI check for an upper size budget (target under 12 MB each), but generate
GIFs intentionally on release rather than on every commit.

## 15. Decisions required from the product owner

Defaults below allow implementation to start, but answers should become ADRs:

1. **Primary launch user:** founder/solo team first, or multi-client agency first?
   Default: founder/team UX with multi-tenant foundations and agency UX in Phase 5.
2. **Deployment promise:** strict local/self-hosted only, or optional managed
   FastFunnel cloud? Default: self-hosted core with clean interfaces for a later
   managed control plane.
3. **Autonomy default:** recommend-only, per-action approval, or bounded autonomous
   posting/spend? Default: recommend-only; users explicitly elevate action classes.
4. **Buffer compatibility:** behavioral parity with a FastFunnel API, or make
   existing Buffer GraphQL clients work with minimal changes? Default: behavioral
   parity first; compatibility only if a concrete client/customer requires it.
5. **Publishing priority after LinkedIn:** X/Instagram, or open networks such as
   Bluesky/Mastodon? Default: one open network to prove the adapter, then
   Instagram/Facebook based on demand.
6. **LLM/provider policy:** OpenAI default, fully provider-neutral, or local-model
   first? Default: provider-neutral gateway with one documented hosted default and
   an Ollama-compatible local profile.
7. **Warehouse baseline:** Postgres-only production, or DuckDB/SQLite as a fully
   supported single-user analytics mode? Default: Postgres production; SQLite
   demo, DuckDB optional for local analysis/export.
8. **Workflow engine:** keep a lightweight Postgres worker through 1.0, or adopt
   Temporal early? Default: Postgres worker with a portability interface; revisit
   after Phase 3 load/reliability evidence.
9. **Marketing Skills update policy:** automatically open periodic update PRs, or
   update only on a maintainer command? The complete MIT pack is vendored either
   way. Default: scheduled update-check issue/PR, never automatic runtime changes.
10. **Design system:** closely inherit the benchmark cockpit layout or establish a
    distinct FastFunnel visual system? Decision: reuse effective interaction
    patterns with a distinct light FastFunnel identity and design tokens.
11. **First real dogfood workspace:** which brand/accounts supply safe test data,
    and who may approve live posts/ad changes?
12. **Commercial boundary:** must every capability remain Apache-2.0, or may a
    future hosted edition have proprietary operational features? Default: all core
    cockpit, connectors, API/MCP, and agency workflows remain Apache-2.0.

## 16. Recommended immediate next sprint

After decisions 1–6:

1. Add ADRs, `AGENTS.md`, `pyproject.toml`, CI, and contributor/security docs.
2. Vendor the complete pinned Marketing Skills repository with its MIT license
   and generate the 49 skill manifests.
3. Scaffold the package layout and FastHTML cockpit shell, including the full
   Skills and Integrations sidebar/catalog with honest stub states.
4. Create tenant, workspace, context, connection, content, publication, approval,
   audit, job, and raw-object migrations.
5. Implement synthetic seed and deterministic demo workspace.
6. Implement the content/review/publication state machines without external APIs.
7. Define adapter capability/Pydantic contracts and provider conformance tests.
8. Port Google/Meta/LinkedIn fixture normalizers from the two benchmark repos.
9. Implement the Postgres worker, sync-run UI, and SSE job stream.
10. Add the initial dashboard/content/review/calendar/integrations pages.
11. Capture the first closed-loop GIF and replace the placeholder README.

The first sprint should prove the architecture with synthetic data. Credential
work starts only after the domain state machines, policy interception, and
idempotency contracts are tested.

## 17. Research sources

Primary/current references reviewed for this plan:

- Funnel Data Hub: <https://funnel.io/data-hub>
- Supermetrics platform: <https://supermetrics.com/platform>
- Supermetrics connector builder:
  <https://docs.supermetrics.com/docs/connector-builder>
- Buffer API introduction:
  <https://developers.buffer.com/guides/introduction.html>
- Buffer posts and scheduling:
  <https://developers.buffer.com/guides/posts-and-scheduling.html>
- Buffer ideas: <https://developers.buffer.com/guides/ideas.html>
- Buffer authentication:
  <https://developers.buffer.com/guides/authentication.html>
- Buffer API limits:
  <https://developers.buffer.com/guides/api-limits.html>
- Marketing Skills:
  <https://github.com/coreyhaines31/marketingskills>
- Google Ads API: <https://developers.google.com/google-ads/api>
- LinkedIn Advertising API:
  <https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/ads-overview>
- LinkedIn current Marketing API changes:
  <https://learn.microsoft.com/en-us/linkedin/marketing/integrations/recent-changes>
- Composio sessions via MCP:
  <https://docs.composio.dev/docs/sessions-via-mcp>
- Composio LinkedIn Ads toolkit:
  <https://docs.composio.dev/toolkits/linkedin_ads>
- Arcade MCP gateways:
  <https://docs.arcade.dev/en/guides/mcp-gateways>
- Arcade LinkedIn tools:
  <https://docs.arcade.dev/en/resources/integrations/social/linkedin>
