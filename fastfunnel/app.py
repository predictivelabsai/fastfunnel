from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fasthtml.common import *
from starlette.responses import RedirectResponse

from fastfunnel.agents import build_agency_graph
from fastfunnel.config import ROOT, settings
from fastfunnel.domain.store import store
from fastfunnel.integrations import CATEGORIES, all_integrations, get_integration
from fastfunnel.integrations.postmark import PostmarkInvitations
from fastfunnel.skills import discover_skills, upstream
from fastfunnel.web.ui import integration_group_counts, shell, status_badge

app, rt = fast_app(
    hdrs=(
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Link(rel="preconnect", href="https://fonts.googleapis.com"),
        Link(
            rel="stylesheet",
            href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap",
        ),
        Link(rel="icon", href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22><text y=%22.9em%22 font-size=%2290%22>⚡</text></svg>"),
        Style((ROOT / "fastfunnel" / "web" / "static" / "app.css").read_text()),
    )
)
store.initialize()


def metric(label: str, value: str, note: str):
    return Div(Small(label), Strong(value), Span(note, cls="delta"), cls="card metric")


@rt("/", methods=["GET"])
def dashboard_view():
    data = store.dashboard()
    counts = data["counts"]
    return shell(
        "Good morning, Predictive Labs",
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
def content_view():
    items = store.list_content()
    return shell(
        "Ideas & content",
        Div(
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
def create_content(title: str, body: str, channel: str):
    store.create_content(title.strip(), body.strip(), channel)
    return RedirectResponse("/review", status_code=303)


@rt("/review", methods=["GET"])
def review_view():
    items = [item for item in store.list_content() if item["status"] == "review"]
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
        active="/review",
    )


@rt("/review/{item_id}/approve", methods=["POST"])
def approve_content(item_id: str):
    store.approve_content(item_id)
    scheduled = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0).isoformat()
    store.schedule_content(item_id, scheduled)
    return RedirectResponse("/calendar", status_code=303)


@rt("/calendar", methods=["GET"])
def calendar_view():
    items = [item for item in store.list_content() if item["status"] in {"scheduled", "published"}]
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
def analytics_view():
    return shell(
        "Analytics",
        Div(
            metric("SPEND", "£0", "Awaiting connection"),
            metric("QUALIFIED LEADS", "0", "Dogfood baseline"),
            metric("COST / LEAD", "—", "No blended data"),
            metric("CONTENT REACH", "—", "No live publishers"),
            cls="grid metrics",
        ),
        Div(
            H2("Governed measurement starts with honest empty states"),
            P(
                "Connect ad, analytics and revenue sources to build the immutable raw → "
                "canonical → semantic pipeline."
            ),
            A("Configure integrations", href="/integrations", cls="btn"),
            cls="card",
        ),
        active="/analytics",
    )


@rt("/skills", methods=["GET"])
def skills_view():
    skills = discover_skills()
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
def skill_detail_view(skill_id: str):
    skill = next((item for item in discover_skills() if item.id == skill_id), None)
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
            P("External side effects remain disabled until governed tools are connected.", cls="muted"),
            cls="card",
        ),
        active="/skills",
    )


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
def integration_detail_view(integration_id: str):
    item = get_integration(integration_id)
    if not item:
        return Response("Integration not found", status_code=404)
    is_stub = item.status == "stub"
    return shell(
        item.name,
        Div(
            Div(
                status_badge(item.status),
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
                P(
                    "This connector is a visible implementation stub. Required scopes, "
                    "credentials and health checks will appear here."
                    if is_stub
                    else "The adapter contract is available. Live credentials are not configured."
                ),
                Button(
                    "Not implemented" if is_stub else "Configure later",
                    type="button",
                    disabled=True,
                ),
                cls="card",
            ),
            cls="grid two",
        ),
        active=f"/integrations/{integration_id}",
    )


@rt("/team", methods=["GET"])
def team_view():
    data = store.dashboard()
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
def invite_team_member(email: str, role: str):
    _, token = store.invite(email, role)
    PostmarkInvitations().send(
        email,
        f"{settings.base_url}/invites/accept?token={token}",
        settings.seed_company,
    )
    return RedirectResponse("/team", status_code=303)


def main():
    import uvicorn

    uvicorn.run("fastfunnel.app:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
