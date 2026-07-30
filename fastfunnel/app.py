from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

from fasthtml.common import *
from starlette.responses import JSONResponse, RedirectResponse

from fastfunnel.agents import build_agency_graph
from fastfunnel.config import ROOT, settings
from fastfunnel.domain.actions import ActionService
from fastfunnel.domain.analytics import BASE_METRICS, AnalyticsService
from fastfunnel.domain.content import ContentService
from fastfunnel.domain.marketing import MarketingService
from fastfunnel.domain.store import store
from fastfunnel.integrations import (
    CATEGORIES,
    all_integrations,
    get_integration,
    runtime_readiness,
)
from fastfunnel.integrations.postmark import PostmarkInvitations
from fastfunnel.skills import discover_skills, save_overlay, skill_for_company, upstream
from fastfunnel.web import account_auth, google_auth
from fastfunnel.web.api import api
from fastfunnel.web.developer import developer_page
from fastfunnel.web.landing import landing_page
from fastfunnel.web.seo import register_seo_routes
from fastfunnel.web.ui import (
    integration_group_counts,
    set_shell_identity,
    shell,
    status_badge,
)


def auth_before(req, sess):
    if (
        req.url.path
        in {
            "/",
            "/api",
            "/healthz",
            "/developers",
            "/robots.txt",
            "/sitemap.xml",
            "/swagger.json",
        }
        or req.url.path.startswith(("/api/", "/auth/", "/static/"))
    ):
        return None
    if not settings.dev_auth_bypass and not sess.get("user_email"):
        return RedirectResponse("/", status_code=303)
    tenant_context(sess)

app, rt = fast_app(
    secret_key=os.getenv("FASTFUNNEL_SESSION_SECRET", "fastfunnel-change-me"),
    before=Beforeware(auth_before),
    hdrs=(
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Link(rel="preconnect", href="https://fonts.googleapis.com"),
        Link(
            rel="stylesheet",
            href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap",
        ),
        Link(rel="icon", href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22><text y=%22.9em%22 font-size=%2290%22>⚡</text></svg>"),
        Script(src="https://cdn.plot.ly/plotly-2.35.2.min.js"),
        Style((ROOT / "fastfunnel" / "web" / "static" / "app.css").read_text()),
    )
)
app.mount("/api", api)
store.initialize()


def establish_product_session(sess, account: dict) -> tuple[dict, dict]:
    company, user = store.ensure_user_workspace(
        account["email"], account.get("name") or account.get("display_name")
    )
    sess["user_email"] = user["email"]
    sess["company_id"] = company["id"]
    set_shell_identity(company, user)
    return company, user


account_auth.register_fasthtml_routes(
    rt,
    app_name="FastFunnel",
    success_path="/",
    on_login=establish_product_session,
)


@rt("/swagger.json", methods=["GET"])
def swagger_schema():
    return JSONResponse(api.openapi())


@rt("/developers", methods=["GET"])
def developers():
    return developer_page()


@rt("/healthz", methods=["GET"])
def health_check():
    return {"status": "ok"}


def metric(label: str, value: str, note: str):
    return Div(Small(label), Strong(value), Span(note, cls="delta"), cls="card metric")


def tenant_context(sess) -> tuple[dict, dict]:
    email = sess.get("user_email")
    if not email and settings.dev_auth_bypass:
        email = settings.admin_email
    try:
        user = store.user_for_email(email)
        company = store.company_for_user(user["email"], sess.get("company_id"))
    except LookupError:
        company, user = store.ensure_user_workspace(email)
    sess["user_email"] = user["email"]
    sess["company_id"] = company["id"]
    set_shell_identity(company, user)
    return company, user


@rt("/", methods=["GET"])
def dashboard_view(sess):
    if not settings.dev_auth_bypass and not sess.get("user_email"):
        return landing_page()
    company, _ = tenant_context(sess)
    data = store.dashboard(company["id"])
    counts = data["counts"]
    return shell(
        f"Good morning, {company['name']}",
        Section(
            Div(
                H2("Your autonomous agency is ready to build demand."),
                P(
                    "Create, approve and distribute useful AI-platform content—"
                    "then learn from every result."
                ),
            ),
            A("Create content", href="/content", cls="btn"),
            cls="hero",
        ),
        Div(
            metric("CONTENT IN REVIEW", str(counts["review"]), "Admin approval"),
            metric("SCHEDULED", str(counts["scheduled"]), "Bounded autonomy"),
            metric("INTEGRATIONS", str(len(all_integrations())), "Catalog online"),
            metric("MARKETING SKILLS", str(len(discover_skills())), "Pinned upstream"),
            cls="grid metrics",
        ),
        Div(
            Section(
                Div(H2("Agency priorities"), A("Open plan →", href="/plan"), cls="section-head"),
                Div(
                    Div(
                        Small("01 · EDUCATE"),
                        H3("Explain AI platforms clearly"),
                        P("Build trust with practical, auditable and outcome-focused guidance."),
                        cls="card",
                    ),
                    Div(
                        Small("02 · CAPTURE"),
                        H3("Convert high-intent demand"),
                        P("Pair thought leadership with targeted campaigns and focused landing pages."),
                        cls="card",
                    ),
                    cls="grid two",
                ),
            ),
            Section(
                Div(H2("Guardrails"), cls="section-head"),
                Div(
                    P("✓ Drafting and scheduling are bounded autonomous actions."),
                    P("✓ Publishing follows workspace channel limits."),
                    P("! Spend and campaign activation require admin approval."),
                    cls="card",
                ),
            ),
            cls="grid two",
        ),
        active="/",
    )


@rt("/auth/google", methods=["GET"])
def google_start(sess, request):
    if not google_auth.enabled():
        return RedirectResponse("/?error=Google+sign-in+is+not+configured", status_code=303)
    state = google_auth.new_state()
    sess["google_oauth_state"] = state
    return RedirectResponse(google_auth.authorize_url(request, state), status_code=303)


@rt("/auth/google/callback", methods=["GET"])
def google_callback(sess, request, code: str = "", state: str = "", error: str = ""):
    if error or not code or state != sess.pop("google_oauth_state", None):
        return RedirectResponse("/?error=Google+sign-in+failed", status_code=303)
    identity = google_auth.exchange(request, code)
    if not identity:
        return RedirectResponse("/?error=Google+account+is+not+authorised", status_code=303)
    account = account_auth.accounts.link_google(identity["email"], identity["name"])
    establish_product_session(sess, account)
    return RedirectResponse("/", status_code=303)


@rt("/plan", methods=["GET"])
def plan_view():
    return shell(
        "Marketing plan",
        Div(
            Div(
                Small("NORTH STAR"),
                H2("Qualified AI platform engagements"),
                P("Help organizations design and deliver auditable AI-first platforms."),
                cls="card",
            ),
            Div(
                Small("OPERATING MODEL"),
                H2("Bounded autonomous"),
                P("The LangGraph agency may research, draft and schedule. Admin approves spend."),
                cls="card",
            ),
            cls="grid two",
        ),
        Div(H2("90-day workstreams"), cls="section-head"),
        Div(
            *[
                Div(Small(f"WORKSTREAM {i:02}"), H3(title), P(copy), cls="card")
                for i, (title, copy) in enumerate(
                    [
                        ("AI platform education", "Guides, architecture explainers and expert-led posts."),
                        ("High-intent acquisition", "Targeted campaigns and conversion-focused landing pages."),
                        ("Trust and proof", "Customer outcomes, transparent pricing and FAQs."),
                    ],
                    1,
                )
            ],
            cls="grid cards",
        ),
        active="/plan",
    )


@rt("/agency", methods=["GET"])
def agency_view():
    graph = build_agency_graph()
    result = graph.invoke(
        {
            "company_id": "co_predictivelabs",
            "goal": "Increase qualified AI platform consulting engagements",
            "messages": [],
        }
    )
    return shell(
        "Autonomous agency",
        Div(
            Div(
                Small("LANGGRAPH RUN"),
                H2("Observe → plan → policy gate"),
                P("This preview is deterministic and performs no external writes."),
                status_badge(result["status"]),
                cls="card",
            ),
            Div(
                Small("APPROVAL OWNER"),
                H2(settings.admin_email),
                P("All high-risk proposals are held for this administrator."),
                cls="card",
            ),
            cls="grid two",
        ),
        Div(H2("Latest proposals"), cls="section-head"),
        Div(
            *[
                Div(
                    status_badge("review" if proposal["requires_approval"] else "approved"),
                    H3(proposal["summary"]),
                    P(f"Risk: {proposal['risk']} · Action: {proposal['type']}"),
                    cls="card",
                )
                for proposal in result["proposals"]
            ],
            cls="grid two",
        ),
        active="/agency",
    )


@rt("/content", methods=["GET"])
def content_view(sess):
    company, _ = tenant_context(sess)
    items = store.list_content(company["id"])
    return shell(
        "Ideas & content",
        Div(
            Div(
                H2("Generate from Marketing Skills"),
                Form(
                    Label(
                        "Goal",
                        Input(
                            name="goal",
                            required=True,
                            placeholder="Explain how governed AI platforms reduce delivery risk",
                        ),
                    ),
                    Label(
                        "Channel",
                        Select(
                            Option("LinkedIn", value="linkedin"),
                            Option("Instagram", value="instagram"),
                            Option("Facebook", value="facebook"),
                            Option("X", value="x"),
                            name="channel",
                        ),
                    ),
                    Button("Generate review draft", type="submit"),
                    method="post",
                    action="/content/generate",
                    cls="stack",
                ),
                P(
                    "Uses the immutable upstream Social skill plus your editable workspace overlay.",
                    cls="muted",
                ),
                cls="card",
            ),
            Div(
                H2("Create a channel-ready draft"),
                Form(
                    Label("Title", Input(name="title", required=True, placeholder="A clear working title")),
                    Label(
                        "Channel",
                        Select(
                            Option("LinkedIn", value="linkedin"),
                            Option("Instagram", value="instagram"),
                            Option("Facebook", value="facebook"),
                            Option("X", value="x"),
                            name="channel",
                        ),
                    ),
                    Label(
                        "Draft",
                        Textarea(
                            name="body",
                            required=True,
                            placeholder="Explain AI-first platforms in clear, useful language…",
                        ),
                    ),
                    Button("Send to review", type="submit"),
                    method="post",
                    action="/content",
                    cls="stack",
                ),
                cls="card",
            ),
            Div(
                H2("Content pipeline"),
                *(
                    [
                        Div(
                            status_badge(item["status"]),
                            H3(item["title"]),
                            P(item["body"][:180]),
                            Small(item["channel"].title()),
                            cls="card",
                        )
                        for item in items[:4]
                    ]
                    or [Div("No content yet. Create the first draft.", cls="empty")]
                ),
            ),
            cls="grid two",
        ),
        active="/content",
    )


@rt("/content", methods=["POST"])
def create_content(sess, title: str, body: str, channel: str):
    company, user = tenant_context(sess)
    store.create_content(
        title.strip(),
        body.strip(),
        channel,
        company_id=company["id"],
        actor_id=user["id"],
    )
    return RedirectResponse("/review", status_code=303)


@rt("/content/generate", methods=["POST"])
def generate_content(sess, goal: str, channel: str):
    company, user = tenant_context(sess)
    ContentService(store).create_draft(
        company_id=company["id"],
        actor_id=user["id"],
        goal=goal,
        channel=channel,
    )
    return RedirectResponse("/review", status_code=303)


@rt("/review", methods=["GET"])
def review_view(sess):
    company, _ = tenant_context(sess)
    items = [
        item for item in store.list_content(company["id"]) if item["status"] == "review"
    ]
    with store.connect() as conn:
        actions = conn.execute(
            """SELECT * FROM action_requests
               WHERE company_id=? AND status='awaiting_approval'
               ORDER BY created_at DESC""",
            (company["id"],),
        ).fetchall()
    rows = [
        Tr(
            Td(status_badge(item["status"])),
            Td(Strong(item["title"]), Br(), Small(item["body"][:180])),
            Td(item["channel"].title()),
            Td(
                Form(
                    Button("Approve", type="submit"),
                    method="post",
                    action=f"/review/{item['id']}/approve",
                )
            ),
        )
        for item in items
    ]
    return shell(
        "Review inbox",
        Div(
            H2("Human review remains the quality boundary"),
            P("Approve an exact revision before bounded autonomous scheduling."),
            Table(
                Thead(Tr(Th("State"), Th("Content"), Th("Channel"), Th("Action"))),
                Tbody(*rows),
                cls="table",
            )
            if rows
            else Div("Nothing is waiting for review.", cls="empty"),
            cls="card",
        ),
        Div(
            H2("External action approvals"),
            P("Approval is bound to the exact payload hash shown in the audit log."),
            Table(
                Thead(Tr(Th("Action"), Th("Provider"), Th("Risk"), Th("Decision"))),
                Tbody(
                    *[
                        Tr(
                            Td(action["action_type"]),
                            Td(action["provider"]),
                            Td(status_badge(action["risk"])),
                            Td(
                                Form(
                                    Button("Approve exact payload", type="submit"),
                                    method="post",
                                    action=f"/actions/{action['id']}/approve",
                                )
                            ),
                        )
                        for action in actions
                    ]
                ),
                cls="table",
            )
            if actions
            else Div("No external mutations are awaiting approval.", cls="empty"),
            cls="card",
        ),
        active="/review",
    )


@rt("/review/{item_id}/approve", methods=["POST"])
def approve_content(sess, item_id: str):
    company, user = tenant_context(sess)
    store.approve_content(item_id, company_id=company["id"], reviewer_id=user["id"])
    scheduled = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0).isoformat()
    store.schedule_content(
        item_id, scheduled, company_id=company["id"], actor_id=user["id"]
    )
    return RedirectResponse("/calendar", status_code=303)


@rt("/calendar", methods=["GET"])
def calendar_view(sess):
    company, _ = tenant_context(sess)
    items = [
        item
        for item in store.list_content(company["id"])
        if item["status"] in {"scheduled", "published"}
    ]
    return shell(
        "Publishing calendar",
        Div(
            H2("Bounded autonomous queue"),
            P("Approved content is assigned the next safe slot. Live dispatch adapters are not enabled yet."),
            *(
                [
                    Div(
                        status_badge(item["status"]),
                        H3(item["title"]),
                        P(item["body"]),
                        Small(f"{item['channel'].title()} · {item['scheduled_for']}"),
                        Form(
                            Select(
                                Option("Arcade", value="arcade"),
                                Option("Composio", value="composio"),
                                name="provider",
                            ),
                            Button(
                                "Request publication approval",
                                type="submit",
                                disabled=item["status"] == "published",
                            ),
                            method="post",
                            action=f"/publish/{item['id']}/propose",
                            cls="funnel-filter",
                        ),
                        cls="card",
                    )
                    for item in items
                ]
                or [Div("Approve a draft to place it in the queue.", cls="empty")]
            ),
            cls="grid",
        ),
        active="/calendar",
    )


@rt("/publish/{item_id}/propose", methods=["POST"])
def propose_publication(sess, item_id: str, provider: str):
    company, user = tenant_context(sess)
    if provider not in {"arcade", "composio"}:
        return Response("Unsupported provider", status_code=422)
    with store.connect() as conn:
        item = conn.execute(
            """SELECT * FROM content_items
               WHERE id=? AND company_id=? AND status='scheduled'""",
            (item_id, company["id"]),
        ).fetchone()
    if not item:
        return Response("Scheduled content not found", status_code=404)
    tools = {
        ("arcade", "linkedin"): "LinkedIn.CreatePost",
        ("arcade", "x"): "X.PostTweet",
        ("composio", "linkedin"): "LINKEDIN_CREATE_POST",
        ("composio", "x"): "TWITTER_CREATION_OF_A_POST",
    }
    tool = tools.get((provider, item["channel"]))
    if not tool:
        return Response("No governed tool mapping for this channel/provider", status_code=422)
    ActionService(store).propose(
        company_id=company["id"],
        actor_id=user["id"],
        action_type="content.publish",
        provider=provider,
        object_type="content",
        object_id=item_id,
        payload={"tool": tool, "text": item["body"]},
        idempotency_key=f"publish:{item_id}:{item['updated_at']}:{provider}",
    )
    return RedirectResponse("/review", status_code=303)


@rt("/actions/{request_id}/approve", methods=["POST"])
def approve_action(sess, request_id: str):
    _, user = tenant_context(sess)
    ActionService(store).approve(request_id, reviewer_id=user["id"])
    return RedirectResponse("/review", status_code=303)


@rt("/campaigns", methods=["GET"])
def campaigns_view():
    return shell(
        "Paid campaigns",
        Div(
            H2("Google, Meta and LinkedIn Ads"),
            P(
                "Reporting contracts are available. Live account credentials and mutation adapters "
                "are not configured."
            ),
            Div(
                *[
                    Div(status_badge("available"), H3(name), P(detail), A("View setup", href=href), cls="card")
                    for name, detail, href in [
                        ("Google Ads", "Campaign reads, reporting and paused creation.", "/integrations/google-ads"),
                        ("Meta Ads", "Campaign reads, insights and paused creation.", "/integrations/meta-ads"),
                        ("LinkedIn Ads", "Versioned reporting; writes depend on access tier.", "/integrations/linkedin-ads"),
                    ]
                ],
                cls="grid cards",
            ),
            cls="card",
        ),
        active="/campaigns",
    )


@rt("/analytics", methods=["GET"])
def analytics_view(sess):
    company, _ = tenant_context(sess)
    summary = MarketingService(store).analytics_summary(company["id"])
    metrics = summary["metrics"]
    spend = metrics.get("spend", 0)
    conversions = metrics.get("conversions", 0)
    clicks = metrics.get("clicks", 0)
    impressions = metrics.get("impressions", 0)
    latest = summary["latest_sync"]
    return shell(
        "Analytics",
        Div(
            metric("SPEND", f"£{spend:,.0f}", "Synthetic Google Ads"),
            metric("CONVERSIONS", f"{conversions:,.0f}", "Platform-reported"),
            metric(
                "COST / CONVERSION",
                f"£{spend / conversions:,.2f}" if conversions else "—",
                "30-day blended",
            ),
            metric(
                "CLICK-THROUGH RATE",
                f"{clicks / impressions * 100:.2f}%" if impressions else "—",
                f"{impressions:,.0f} impressions",
            ),
            cls="grid metrics",
        ),
        Div(
            Div(
                Div(
                    Small("LATEST INGESTION"),
                    H2("Google Ads reporting is flowing"),
                    P(
                        f"{latest['rows_written']:,} normalized facts · "
                        f"{latest['status']} · {latest['finished_at'][:19]} UTC"
                    )
                    if latest
                    else P("No completed sync."),
                ),
                Div(
                    A("Explore KPIs", href="/analytics/explorer", cls="btn"),
                    A("Open acquisition funnel", href="/analytics/funnel", cls="btn"),
                    cls="top-actions",
                ),
                cls="hero",
            ),
            P(
                "The launch dataset is deterministic synthetic data through the same "
                "read contract used by the future live connector. GA4 remains visibly "
                "unconnected until credentials are supplied."
            ),
            cls="card",
        ),
        active="/analytics",
    )


@rt("/analytics/funnel", methods=["GET"])
def funnel_view(sess, days: int = 30):
    company, _ = tenant_context(sess)
    days = max(1, min(int(days), 90))
    result = MarketingService(store).funnel(days=days, company_id=company["id"])
    definition = result["definition"]
    trace_json = json.dumps([result["trace"]])
    layout_json = json.dumps(
        {
            "height": 470,
            "margin": {"l": 18, "r": 18, "t": 24, "b": 18},
            "paper_bgcolor": "white",
            "plot_bgcolor": "white",
            "font": {"family": "Inter, sans-serif", "size": 11, "color": "#172033"},
        }
    )
    rows = [
        Tr(
            Td(stage.name),
            Td(f"{result['values'][index]:,}"),
            Td(
                "—"
                if result["step_conversion"][index] is None
                else f"{result['step_conversion'][index]:.1f}%"
            ),
            Td(
                "—"
                if result["overall_conversion"][index] is None
                else f"{result['overall_conversion'][index]:.1f}%"
            ),
        )
        for index, stage in enumerate(result["stages"])
    ]
    return shell(
        "Acquisition funnel",
        Div(
            Div(
                Div(
                    Small("CONFIGURABLE FUNNEL · SYNTHETIC COHORT"),
                    H2(definition["name"]),
                    P(
                        f"{definition['description']} Cohort since {result['since']} "
                        f"({days} days)."
                    ),
                ),
                Form(
                    Label(
                        "Window",
                        Select(
                            *[
                                Option(
                                    f"{value} days",
                                    value=str(value),
                                    selected=value == days,
                                )
                                for value in (7, 14, 30, 60, 90)
                            ],
                            name="days",
                        ),
                    ),
                    Button("Apply", type="submit"),
                    method="get",
                    action="/analytics/funnel",
                    cls="funnel-filter",
                ),
                cls="hero",
            ),
            Div(id="acquisition-sankey", cls="sankey-chart"),
            Script(
                NotStr(
                    "Plotly.newPlot('acquisition-sankey',"
                    f"{trace_json},{layout_json},"
                    "{displayModeBar:false,responsive:true});"
                )
            ),
            cls="card",
        ),
        Div(
            Div(H2("Stage metrics"), Small("Conserved cohort counts"), cls="section-head"),
            Table(
                Thead(Tr(Th("Stage"), Th("People"), Th("From previous"), Th("Overall"))),
                Tbody(*rows),
                cls="table",
            ),
            cls="card",
        ),
        active="/analytics/funnel",
    )


@rt("/analytics/explorer", methods=["GET"])
def explorer_view(sess, metric_name: str = "clicks", dimension: str = "fact_date"):
    company, _ = tenant_context(sess)
    if metric_name not in BASE_METRICS:
        metric_name = "clicks"
    if dimension not in {"fact_date", "provider", "campaign"}:
        dimension = "fact_date"
    analytics = AnalyticsService(store)
    rows = analytics.explore(
        company_id=company["id"], metric=metric_name, dimension=dimension
    )
    kpis = analytics.kpis(company["id"])
    return shell(
        "KPI explorer",
        Div(
            *[
                metric(
                    item["name"].upper(),
                    (
                        f"{item['value'] * 100:.2f}%"
                        if item["format"] == "percent"
                        else f"£{item['value']:,.2f}"
                        if item["format"] == "currency"
                        else f"{item['value']:,.2f}"
                    ),
                    f"{item['numerator_metric']} / {item['denominator_metric']}",
                )
                for item in kpis
            ],
            cls="grid metrics",
        ),
        Div(
            Form(
                Label(
                    "Metric",
                    Select(
                        *[
                            Option(name.replace("_", " ").title(), value=name,
                                   selected=name == metric_name)
                            for name in sorted(BASE_METRICS)
                        ],
                        name="metric_name",
                    ),
                ),
                Label(
                    "Dimension",
                    Select(
                        *[
                            Option(name.replace("_", " ").title(), value=name,
                                   selected=name == dimension)
                            for name in ("fact_date", "provider", "campaign")
                        ],
                        name="dimension",
                    ),
                ),
                Button("Run", type="submit"),
                method="get",
                action="/analytics/explorer",
                cls="funnel-filter",
            ),
            Table(
                Thead(Tr(Th(dimension.replace("_", " ").title()), Th(metric_name.title()))),
                Tbody(*[Tr(Td(row["dimension"]), Td(f"{row['value']:,.2f}")) for row in rows]),
                cls="table",
            ),
            cls="card",
        ),
        active="/analytics/explorer",
    )


@rt("/skills", methods=["GET"])
def skills_view(sess):
    company, _ = tenant_context(sess)
    skills = discover_skills(store, company["id"])
    source = upstream()
    return shell(
        "Marketing skills",
        Div(
            Div(
                H2(f"{len(skills)} bundled skills"),
                P(
                    f"Pinned to {source.get('commit', 'unknown')[:12]} · MIT licensed · "
                    "workspace context is applied as an overlay."
                ),
            ),
            cls="hero",
        ),
        Div(
            *[
                Div(
                    status_badge(skill.status),
                    H3(skill.title),
                    P(skill.summary),
                    A("Inspect skill", href=f"/skills/{skill.id}"),
                    cls="card catalog-card",
                )
                for skill in skills
            ],
            cls="grid cards",
            style="margin-top:18px",
        ),
        active="/skills",
    )


@rt("/skills/{skill_id}", methods=["GET"])
def skill_detail_view(sess, skill_id: str):
    company, _ = tenant_context(sess)
    skill = skill_for_company(store, company["id"], skill_id)
    if not skill:
        return Response("Skill not found", status_code=404)
    excerpt = skill.path.read_text(errors="replace")[:1400] if skill.path.exists() else ""
    return shell(
        skill.title,
        Div(
            status_badge(skill.status),
            H2(skill.title),
            P(skill.summary),
            H3("Bundled instructions"),
            Pre(excerpt),
            H3("Workspace overlay"),
            Form(
                Label(
                    "Additional instructions",
                    Textarea(
                        skill.overlay_instructions,
                        name="instructions",
                        rows="12",
                        placeholder="Add brand voice, audience, exclusions, and workflow rules…",
                    ),
                ),
                Label(
                    Input(type="checkbox", name="enabled", value="1", checked=skill.enabled),
                    " Enabled for this workspace",
                ),
                Button("Save workspace overlay", type="submit"),
                method="post",
                action=f"/skills/{skill.id}",
                cls="stack",
            ),
            P(
                "Upstream instructions remain immutable; this tenant-scoped overlay is versioned.",
                cls="muted",
            ),
            cls="card",
        ),
        active="/skills",
    )


@rt("/skills/{skill_id}", methods=["POST"])
def update_skill_overlay(sess, skill_id: str, instructions: str = "", enabled: str = ""):
    company, user = tenant_context(sess)
    save_overlay(
        store,
        company["id"],
        skill_id,
        instructions,
        enabled=enabled == "1",
        actor_id=user["id"],
    )
    return RedirectResponse(f"/skills/{skill_id}", status_code=303)


@rt("/integrations", methods=["GET"])
def integrations_view():
    counts = integration_group_counts()
    return shell(
        "Integrations",
        Div(
            *[
                Div(
                    Small(category.upper()),
                    H2(str(counts[category])),
                    P("Available and planned connectors"),
                    cls="card metric",
                )
                for category in CATEGORIES
            ],
            cls="grid cards",
        ),
        *[
            Section(
                Div(H2(category), cls="section-head"),
                Div(
                    *[
                        Div(
                            status_badge(item.status),
                            H3(item.name),
                            P(item.description),
                            Div(*[Span(route, cls="route") for route in item.routes]),
                            A("Open setup →", href=f"/integrations/{item.id}", style="margin-top:12px"),
                            cls="card catalog-card",
                        )
                        for item in all_integrations()
                        if item.category == category
                    ],
                    cls="grid cards",
                ),
            )
            for category in CATEGORIES
        ],
        active="/integrations",
    )


@rt("/integrations/{integration_id}", methods=["GET"])
def integration_detail_view(sess, integration_id: str):
    company, user = tenant_context(sess)
    item = get_integration(integration_id)
    if not item:
        return Response("Integration not found", status_code=404)
    runtime_status, runtime_reason = runtime_readiness(integration_id)
    is_stub = runtime_status == "stub"
    return shell(
        item.name,
        Div(
            Div(
                status_badge(runtime_status),
                H2(item.name),
                P(item.description),
                H3("Provider routes"),
                Div(*[Span(route, cls="route") for route in item.routes]),
                H3("Capabilities", style="margin-top:18px"),
                Ul(*[Li(capability) for capability in item.capabilities]),
                cls="card",
            ),
            Div(
                H2("Setup"),
                P(runtime_reason),
                (
                    Form(
                        Label(
                            "Provider user ID",
                            Input(
                                name="external_user_id",
                                value=f"{company['id']}:{user['id']}",
                                required=True,
                            ),
                        ),
                        Label(
                            "Connected account reference",
                            Input(
                                name="connected_account_id",
                                placeholder="Returned by hosted provider authorization",
                                required=True,
                            ),
                        ),
                        Button("Save delegated account", type="submit"),
                        method="post",
                        action=f"/integrations/{integration_id}/identity",
                        cls="stack",
                    )
                    if integration_id in {"composio", "arcade"}
                    and runtime_status == "connected"
                    else Form(
                        Input(type="hidden", name="mode", value="synthetic"),
                        Button("Run synthetic contract sync", type="submit"),
                        method="post",
                        action=f"/integrations/{integration_id}/sync",
                    )
                    if integration_id in {"hubspot", "brevo", "ga4"}
                    else ""
                ),
                Button(
                    "Not implemented"
                    if is_stub
                    else "Connected"
                    if runtime_status == "connected"
                    else "Credentials required",
                    type="button",
                    disabled=True,
                ),
                cls="card",
            ),
            cls="grid two",
        ),
        active=f"/integrations/{integration_id}",
    )


@rt("/integrations/{integration_id}/identity", methods=["POST"])
def save_provider_identity(
    sess,
    integration_id: str,
    external_user_id: str,
    connected_account_id: str,
):
    if integration_id not in {"composio", "arcade"}:
        return Response("Unsupported delegated provider", status_code=422)
    if runtime_readiness(integration_id)[0] != "connected":
        return Response("Provider API key is not configured", status_code=503)
    company, user = tenant_context(sess)
    timestamp = datetime.now(UTC).isoformat()
    with store.connect() as conn:
        conn.execute(
            """INSERT INTO provider_identities
               (id, company_id, user_id, provider, external_user_id,
                connected_account_id, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'connected', ?, ?)
               ON CONFLICT(company_id, user_id, provider) DO UPDATE SET
                 external_user_id=excluded.external_user_id,
                 connected_account_id=excluded.connected_account_id,
                 status='connected', updated_at=excluded.updated_at""",
            (
                f"pid_{company['id']}_{user['id']}_{integration_id}",
                company["id"],
                user["id"],
                integration_id,
                external_user_id.strip(),
                connected_account_id.strip(),
                timestamp,
                timestamp,
            ),
        )
        store._audit(
            conn,
            company["organization_id"],
            company["id"],
            user["id"],
            "provider.identity.connected",
            "integration",
            integration_id,
            {"external_user_id": external_user_id.strip()},
        )
    return RedirectResponse(f"/integrations/{integration_id}", status_code=303)


@rt("/integrations/{integration_id}/sync", methods=["POST"])
def enqueue_source_sync(sess, integration_id: str, mode: str = "synthetic"):
    company, _ = tenant_context(sess)
    if integration_id not in {"hubspot", "brevo", "ga4"}:
        return Response("Unsupported source", status_code=422)
    if mode not in {"synthetic", "live"}:
        return Response("Unsupported mode", status_code=422)
    timestamp = datetime.now(UTC).isoformat()
    with store.connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO job_queue
               (id, company_id, job_type, payload_json, idempotency_key,
                status, available_at, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                f"job_{integration_id}_{datetime.now(UTC).timestamp()}",
                company["id"],
                f"sync.{integration_id}",
                json.dumps({"mode": mode, "lookback_days": 30}),
                f"sync:{integration_id}:{mode}:{datetime.now(UTC).date()}",
                timestamp,
                timestamp,
            ),
        )
    return RedirectResponse(f"/integrations/{integration_id}", status_code=303)


@rt("/team", methods=["GET"])
def team_view(sess):
    company, _ = tenant_context(sess)
    data = store.dashboard(company["id"])
    return shell(
        "Team & invites",
        Div(
            Div(
                H2("Invite a teammate"),
                P("Postmark delivery will activate when a server token is configured."),
                Form(
                    Label("Email", Input(type="email", name="email", required=True)),
                    Label(
                        "Role",
                        Select(
                            Option("Creator", value="creator"),
                            Option("Reviewer", value="reviewer"),
                            Option("Analyst", value="analyst"),
                            Option("Admin", value="admin"),
                            name="role",
                        ),
                    ),
                    Button("Create invitation", type="submit"),
                    method="post",
                    action="/team/invite",
                    cls="stack",
                ),
                cls="card",
            ),
            Div(
                H2("Members"),
                Table(
                    Tbody(
                        *[
                            Tr(Td(member["display_name"]), Td(member["email"]), Td(status_badge(member["role"])))
                            for member in data["members"]
                        ]
                    ),
                    cls="table",
                ),
                H2("Pending invitations", style="margin-top:20px"),
                *(
                    [
                        P(f"{invite['email']} · {invite['role']} · delivery pending")
                        for invite in data["invitations"]
                    ]
                    or [P("No pending invitations.", cls="muted")]
                ),
                cls="card",
            ),
            cls="grid two",
        ),
        active="/team",
    )


@rt("/team/invite", methods=["POST"])
def invite_team_member(sess, email: str, role: str):
    company, user = tenant_context(sess)
    _, token = store.invite(
        email,
        role,
        company_id=company["id"],
        actor_id=user["id"],
    )
    PostmarkInvitations().send(
        email,
        f"{settings.base_url}/invites/accept?token={token}",
        company["name"],
    )
    return RedirectResponse("/team", status_code=303)



register_seo_routes(app)

def main():
    import uvicorn

    uvicorn.run("fastfunnel.app:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
