from __future__ import annotations

from fasthtml.common import *

from fastfunnel.integrations import CATEGORIES, all_integrations


def icon(name: str) -> Span:
    glyphs = {
        "dashboard": "⌂", "plan": "◇", "agency": "✦", "content": "✎",
        "review": "✓", "calendar": "□", "campaigns": "◎", "analytics": "⌁",
        "funnel": "▽", "skills": "⚡", "integrations": "⌘", "team": "♙",
    }
    return Span(glyphs.get(name, "·"), cls="nav-icon")


def nav_link(label: str, href: str, icon_name: str, active: str) -> A:
    selected = " active" if active == href else ""
    return A(icon(icon_name), Span(label), href=href, cls=f"nav-link{selected}")


def sidebar(active: str = "/") -> Aside:
    integration_links = [
        A(
            Span(item.name),
            Span(item.status, cls=f"tiny-status {item.status}"),
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
            nav_link("Team & Invites", "/team", "team", active),
            nav_link("Developers", "/developers", "integrations", active),
        ),
        cls="sidebar",
    )


def topbar(title: str, eyebrow: str = "PREDICTIVE LABS · AI-FIRST CONSULTANCY") -> Header:
    return Header(
        Div(Small(eyebrow, cls="eyebrow"), H1(title)),
        Div(
            Span("Bounded autonomy", cls="pill success"),
            Span("admin@fastfunnel.app", cls="user-pill"),
            cls="top-actions",
        ),
        cls="topbar",
    )


def shell(title: str, *content, active: str = "/", rail=None):
    return (
        Title(f"{title} · FastFunnel"),
        Div(
            sidebar(active),
            Main(topbar(title), Div(*content, cls="page-content"), cls="main"),
            rail or assistant_rail(),
            cls="app-shell",
        ),
    )


def assistant_rail():
    return Aside(
        Div(Span("✦", cls="spark"), Div(Strong("Agency copilot"), Small("LangGraph swarm")), cls="rail-head"),
        Div(
            P("I can draft, review, distribute and measure—within Predictive Labs' approval policy."),
            Div(Strong("Current guardrail"), P("Publishing is bounded. Spend changes require admin approval."), cls="rail-card"),
            Div(Strong("Suggested"), P("Create a LinkedIn post about building auditable AI platforms."), cls="rail-card accent"),
            cls="rail-body",
        ),
        Form(
            Input(name="message", placeholder="Ask the agency…", disabled=True),
            Button("↑", type="button", disabled=True),
            cls="rail-input",
        ),
        cls="assistant-rail",
    )


def status_badge(status: str):
    return Span(status.replace("-", " "), cls=f"status {status}")


def integration_group_counts():
    return {
        category: len([item for item in all_integrations() if item.category == category])
        for category in CATEGORIES
    }
