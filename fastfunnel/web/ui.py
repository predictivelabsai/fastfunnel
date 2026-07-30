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
        "settings": "⚙", "logout": "↪",
    }
    return Span(glyphs.get(name, "·"), cls="nav-icon")


def nav_link(label: str, href: str, icon_name: str, active: str) -> A:
    selected = " active" if active == href else ""
    return A(icon(icon_name), Span(label), href=href, cls=f"nav-link{selected}")


def nav_section(label: str, section_id: str, *items) -> Details:
    return Details(
        Summary(
            Small(label, cls="nav-label"),
            Span(cls="nav-section-arrow", aria_hidden="true"),
            cls="nav-section-toggle",
            aria_label=f"Expand or collapse {label.title()}",
        ),
        Div(*items, cls="nav-section-items"),
        open=True,
        cls="nav-section",
        data_section=section_id,
    )


def sidebar(
    active: str = "/",
    company: dict | None = None,
    workspaces: list[dict] | None = None,
    user: dict | None = None,
) -> Aside:
    company = company or {}
    workspaces = workspaces or []
    user = user or {}
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
        Div(
            Button(
                "<<",
                type="button",
                id="nav-collapse-all",
                title="Minimise all navigation sections",
                aria_label="Minimise all navigation sections",
            ),
            Button(
                ">>",
                type="button",
                id="nav-expand-all",
                title="Maximise all navigation sections",
                aria_label="Maximise all navigation sections",
            ),
            cls="nav-section-controls",
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
            nav_section(
                "OVERVIEW",
                "overview",
                nav_link("Dashboard", "/", "dashboard", active),
                nav_link("Plan", "/plan", "plan", active),
                nav_link("Agency", "/agency", "agency", active),
            ),
            nav_section(
                "CREATE & SHIP",
                "create-ship",
                nav_link("Ideas & Content", "/content", "content", active),
                nav_link("Review", "/review", "review", active),
                nav_link("Calendar", "/calendar", "calendar", active),
            ),
            nav_section(
                "ACQUISITION",
                "acquisition",
                nav_link("Paid Campaigns", "/campaigns", "campaigns", active),
            ),
            nav_section(
                "MEASURE",
                "measure",
                nav_link("Analytics", "/analytics", "analytics", active),
                nav_link("Growth dashboard", "/analytics/growth", "analytics", active),
                nav_link("KPI Explorer", "/analytics/explorer", "analytics", active),
                nav_link("Acquisition Funnel", "/analytics/funnel", "funnel", active),
            ),
            nav_section(
                "LIBRARY",
                "library",
                nav_link("Skills (49)", "/skills", "skills", active),
                A(
                    icon("integrations"),
                    Span("All integrations"),
                    href="/integrations",
                    cls=(
                        "nav-link active"
                        if active == "/integrations"
                        else "nav-link"
                    ),
                ),
                Details(
                    Summary(
                        icon("integrations"),
                        Span("Provider setup"),
                        cls="nav-link",
                    ),
                    *integration_links,
                    open=active.startswith("/integrations/"),
                    cls="provider-nav",
                ),
            ),
            nav_section(
                "SETTINGS",
                "settings",
                nav_link("Workspace settings", "/settings", "settings", active),
                nav_link("Team & Invites", "/team", "team", active),
                nav_link("Developers", "/developers", "integrations", active),
            ),
        ),
        Div(
            Div(
                Strong(user.get("display_name") or "Signed in"),
                Small(user.get("email", "")),
                cls="sidebar-account-identity",
            ),
            Form(
                Button(
                    icon("logout"),
                    Span("Log out"),
                    type="submit",
                    cls="sidebar-logout",
                    aria_label="Log out of FastFunnel",
                ),
                method="post",
                action="/auth/logout",
            ),
            cls="sidebar-account",
        ),
        Script(
            NotStr(
                """
                (() => {
                  const sections = [...document.querySelectorAll('.nav-section')];
                  const save = section => localStorage.setItem(
                    `fastfunnel:nav:${section.dataset.section}`,
                    section.open ? '1' : '0'
                  );
                  sections.forEach(section => {
                    const stored = localStorage.getItem(
                      `fastfunnel:nav:${section.dataset.section}`
                    );
                    if (stored !== null) section.open = stored === '1';
                    section.addEventListener('toggle', () => save(section));
                  });
                  document.getElementById('nav-collapse-all')?.addEventListener(
                    'click',
                    () => sections.forEach(section => {
                      section.open = false;
                      save(section);
                    })
                  );
                  document.getElementById('nav-expand-all')?.addEventListener(
                    'click',
                    () => sections.forEach(section => {
                      section.open = true;
                      save(section);
                    })
                  );
                })();
                """
            )
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
            sidebar(active, company, workspaces, user),
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
    suggestions = (
        (
            "Diagnose the funnel",
            "Find the largest drop-off and suggest the next measurable test.",
            "Where is our largest funnel drop-off, and what should we test next?",
        ),
        (
            "Plan next week",
            "Turn current campaign and KPI evidence into a focused content plan.",
            "Build a one-week content plan from our current campaign and KPI evidence.",
        ),
        (
            "Explain performance",
            "Compare acquisition channels and clearly label any inference.",
            "Which acquisition channels are underperforming, and what evidence supports that?",
        ),
    )
    return Aside(
        Div(
            Span("✦", cls="spark"),
            Div(
                Strong("Agency copilot"),
                Small("LangChain · workspace model"),
            ),
            cls="rail-head",
        ),
        Div(
            Div(
                P(
                    "Ask about content, acquisition, funnels or KPIs using "
                    f"{company_name}'s live workspace evidence."
                ),
                Span(
                    "Ready to answer" if enabled else "Model setup required",
                    cls=f"status {'connected' if enabled else 'stub'}",
                ),
                cls="rail-intro",
            ),
            Form(
                Textarea(
                    name="message",
                    placeholder=(
                        "Ask the agency to analyse, explain or plan…"
                        if enabled
                        else "Configure a model in Workspace settings"
                    ),
                    minlength="2",
                    maxlength="4000",
                    rows="3",
                    required=True,
                    disabled=not enabled,
                    id="agency-copilot-input",
                ),
                Button(
                    "Ask",
                    type="submit",
                    disabled=not enabled,
                    cls="rail-ask",
                ),
                method="post",
                action="/agency/chat",
                cls="rail-compose",
            ),
            Div(
                Small("TRY ASKING", cls="rail-label"),
                *[
                    Button(
                        Strong(title),
                        Small(detail),
                        type="button",
                        disabled=not enabled,
                        data_prompt=prompt,
                        onclick=(
                            "agencyPrompt(this.dataset.prompt)"
                            if enabled
                            else None
                        ),
                        cls="rail-suggestion",
                    )
                    for title, detail, prompt in suggestions
                ],
                cls="rail-suggestions",
            ),
            (
                A(
                    "Configure the workspace model →",
                    href="/settings",
                    cls="rail-setup-link",
                )
                if not enabled
                else ""
            ),
            Div(
                Strong("Current guardrail"),
                P(
                    "Answers may advise and draft. Publishing and spend changes "
                    "still require the governed approval workflow."
                ),
                cls="rail-card",
            ),
            Div(
                Strong("Grounded answers"),
                P("Uses tenant-scoped content, campaigns, funnels and KPI facts."),
                cls="rail-card accent",
            ),
            cls="rail-body",
        ),
        Script(
            NotStr(
                """
                function agencyPrompt(prompt) {
                  const input = document.getElementById('agency-copilot-input');
                  if (!input || input.disabled) return;
                  input.value = prompt;
                  input.focus();
                }
                """
            )
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
