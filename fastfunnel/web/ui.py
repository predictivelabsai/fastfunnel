from __future__ import annotations

from contextvars import ContextVar

from fasthtml.common import *

from fastfunnel.integrations import CATEGORIES, all_integrations

_shell_identity: ContextVar[tuple[dict, dict, bool, list[dict]] | None] = ContextVar(
    "fastfunnel_shell_identity", default=None
)


def set_shell_identity(
    company: dict,
    user: dict,
    model_ready: bool = False,
    workspaces: list[dict] | None = None,
) -> None:
    _shell_identity.set((company, user, model_ready, workspaces or []))


def icon(name: str) -> Span:
    glyphs = {
        "dashboard": "⌂", "plan": "◇", "agency": "✦", "content": "✎",
        "review": "✓", "calendar": "□", "campaigns": "◎", "analytics": "⌁",
        "funnel": "▽", "skills": "⚡", "integrations": "⌘", "team": "♙",
        "settings": "⚙",
    }
    return Span(glyphs.get(name, "·"), cls="nav-icon")


def nav_link(label: str, href: str, icon_name: str, active: str) -> A:
    selected = " active" if active == href else ""
    return A(icon(icon_name), Span(label), href=href, cls=f"nav-link{selected}")


def sidebar(active: str = "/", company: dict | None = None, workspaces: list[dict] | None = None) -> Aside:
    company = company or {}
    workspaces = workspaces or []
    integration_links = [
        A(
            Span(item.name),
            Span(
                "Coming soon" if item.status == "stub" else item.status,
                cls=f"tiny-status {item.status}",
            ),
            href=f"/integrations/{item.id}",
            cls="nav-link nested",
        )
        for item in all_integrations()
    ]
    return Aside(
        Div(
            Div("FF", cls="logo-mark"),
            Div(Strong("FastFunnel"), Small("Autonomous agency")),
            cls="brand",
        ),
        (
            Form(
                Select(
                    *[
                        Option(
                            f"{item['organization_name']} · {item['name']}",
                            value=item["id"],
                            selected=item["id"] == company.get("id"),
                        )
                        for item in workspaces
                    ],
                    name="company_id",
                    onchange="this.form.submit()",
                    aria_label="Active workspace",
                ),
                method="post",
                action="/workspace/switch",
                cls="workspace-switcher",
            )
            if len(workspaces) > 1
            else ""
        ),
        Nav(
            Small("OVERVIEW", cls="nav-label"),
            nav_link("Dashboard", "/", "dashboard", active),
            nav_link("Plan", "/plan", "plan", active),
            nav_link("Agency", "/agency", "agency", active),
            Small("CREATE & SHIP", cls="nav-label"),
            nav_link("Ideas & Content", "/content", "content", active),
            nav_link("Review", "/review", "review", active),
            nav_link("Calendar", "/calendar", "calendar", active),
            Small("ACQUISITION", cls="nav-label"),
            nav_link("Paid Campaigns", "/campaigns", "campaigns", active),
            Small("MEASURE", cls="nav-label"),
            nav_link("Analytics", "/analytics", "analytics", active),
            nav_link("Growth dashboard", "/analytics/growth", "analytics", active),
            nav_link("KPI Explorer", "/analytics/explorer", "analytics", active),
            nav_link("Acquisition Funnel", "/analytics/funnel", "funnel", active),
            Small("LIBRARY", cls="nav-label"),
            nav_link("Skills (49)", "/skills", "skills", active),
            Details(
                Summary(icon("integrations"), Span("Integrations"), cls="nav-link"),
                *integration_links,
                open=active.startswith("/integrations"),
            ),
            Small("SETTINGS", cls="nav-label"),
            nav_link("Workspace settings", "/settings", "settings", active),
            nav_link("Team & Invites", "/team", "team", active),
            nav_link("Developers", "/developers", "integrations", active),
        ),
        cls="sidebar",
    )


def topbar(
    title: str,
    eyebrow: str = "DIGITAL MARKETING WORKSPACE",
    user_email: str = "",
) -> Header:
    return Header(
        Div(Small(eyebrow, cls="eyebrow"), H1(title)),
        Div(
            Span("Bounded autonomy", cls="pill success"),
            Span(user_email, cls="user-pill") if user_email else "",
            cls="top-actions",
        ),
        cls="topbar",
    )


def shell(title: str, *content, active: str = "/", rail=None):
    identity = _shell_identity.get()
    company, user, model_ready, workspaces = (
        identity if identity else ({}, {}, False, [])
    )
    company_name = company.get("name", "FastFunnel")
    return (
        Title(f"{title} · FastFunnel"),
        Div(
            sidebar(active, company, workspaces),
            Main(
                topbar(
                    title,
                    f"{company_name.upper()} · DIGITAL MARKETING",
                    user.get("email", ""),
                ),
                Div(*content, cls="page-content"),
                cls="main",
            ),
            rail or assistant_rail(company_name, enabled=model_ready),
            cls="app-shell",
        ),
    )


def assistant_rail(company_name: str = "your workspace", *, enabled: bool = False):
    return Aside(
        Div(
            Span("✦", cls="spark"),
            Div(Strong("Agency copilot"), Small("xAI · LangChain")),
            cls="rail-head",
        ),
        Div(
            P(
                "I can draft, review, distribute and measure—within "
                f"{company_name}'s approval policy."
            ),
            Div(Strong("Current guardrail"), P("Publishing is bounded. Spend changes require admin approval."), cls="rail-card"),
            Div(
                Strong("Grounded answers"),
                P("Uses this workspace's content, campaigns and KPI facts."),
                cls="rail-card accent",
            ),
            cls="rail-body",
        ),
        Form(
            Input(
                name="message",
                placeholder=(
                    "Ask the agency…"
                    if enabled
                    else "Configure xAI in Workspace settings"
                ),
                minlength="2",
                maxlength="4000",
                required=True,
                disabled=not enabled,
            ),
            Button(
                "↑",
                type="submit",
                aria_label="Send to agency",
                disabled=not enabled,
            ),
            method="post",
            action="/agency/chat",
            cls="rail-input",
        ),
        cls="assistant-rail",
    )


def status_badge(status: str):
    label = (
        "Coming soon"
        if status == "stub"
        else status.replace("-", " ").replace("_", " ")
    )
    return Span(label, cls=f"status {status}")


def integration_group_counts():
    return {
        category: len([item for item in all_integrations() if item.category == category])
        for category in CATEGORIES
    }
