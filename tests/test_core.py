from pathlib import Path

from fastfunnel.agents import build_agency_graph
from fastfunnel.app import app
from fastfunnel.domain.store import Store
from fastfunnel.integrations import all_integrations, get_integration
from fastfunnel.integrations.postmark import PostmarkInvitations
from fastfunnel.skills import discover_skills, upstream


def test_all_upstream_skills_are_discovered():
    skills = discover_skills()
    assert len(skills) == 49
    assert {skill.id for skill in skills} >= {"ads", "analytics", "social", "attribution"}
    assert upstream()["commit"] == "7868cb9251fad80a73d26e488a5ad5f6c4a9f335"


def test_integration_catalog_contains_launch_and_stub_channels():
    assert len(all_integrations()) >= 30
    assert get_integration("google-ads").status == "available"
    assert get_integration("facebook-instagram").status == "available"
    assert get_integration("x").status == "available"
    assert get_integration("bluesky").status == "stub"
    assert get_integration("mastodon").status == "stub"
    assert get_integration("ga4").status == "stub"


def test_predictive_labs_seed_and_content_workflow(tmp_path: Path):
    store = Store(tmp_path / "test.sqlite3")
    store.initialize()
    data = store.dashboard()
    assert data["company"]["domain"] == "predictivelabs.ai"
    assert data["company"]["name"] == "Predictive Labs"
    assert data["members"][0]["email"] == "admin@fastfunnel.app"

    item_id = store.create_content("Auditable AI platform guide", "Useful draft", "linkedin")
    assert store.list_content()[0]["status"] == "review"
    store.approve_content(item_id)
    store.schedule_content(item_id, "2026-07-29T09:00:00+00:00")
    assert store.list_content()[0]["status"] == "scheduled"


def test_agency_graph_holds_high_risk_actions():
    result = build_agency_graph().invoke(
        {"company_id": "co_predictivelabs", "goal": "Qualified leads", "messages": []}
    )
    assert result["status"] == "bounded"
    assert len(result["proposals"]) == 2
    assert all(not action["requires_approval"] for action in result["approved_actions"])


def test_postmark_is_honest_when_not_configured():
    result = PostmarkInvitations().send(
        "team@example.com", "http://localhost/invite", "Predictive Labs"
    )
    assert result.status == "pending"


def test_content_and_approval_routes_are_method_scoped():
    methods_by_path = {
        route.path: set(route.methods) for route in app.routes if hasattr(route, "methods")
    }
    assert methods_by_path["/"] == {"GET", "HEAD"}
    assert {"GET", "HEAD"} in [
        set(route.methods) for route in app.routes if getattr(route, "path", "") == "/content"
    ]
    assert {"POST"} in [
        set(route.methods) for route in app.routes if getattr(route, "path", "") == "/content"
    ]
    assert methods_by_path["/review/{item_id}/approve"] == {"POST"}
