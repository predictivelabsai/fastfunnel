from pathlib import Path

from fastfunnel.agents import build_agency_graph
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


def test_factorio_seed_and_content_workflow(tmp_path: Path):
    store = Store(tmp_path / "test.sqlite3")
    store.initialize()
    data = store.dashboard()
    assert data["company"]["domain"] == "factorio.co.uk"
    assert data["members"][0]["email"] == "kaljuvee@gmail.com"

    item_id = store.create_content("Invoice finance guide", "Useful draft", "linkedin")
    assert store.list_content()[0]["status"] == "review"
    store.approve_content(item_id)
    store.schedule_content(item_id, "2026-07-29T09:00:00+00:00")
    assert store.list_content()[0]["status"] == "scheduled"


def test_agency_graph_holds_high_risk_actions():
    result = build_agency_graph().invoke(
        {"company_id": "co_factorio", "goal": "Qualified leads", "messages": []}
    )
    assert result["status"] == "bounded"
    assert len(result["proposals"]) == 2
    assert all(not action["requires_approval"] for action in result["approved_actions"])


def test_postmark_is_honest_when_not_configured():
    result = PostmarkInvitations().send(
        "team@example.com", "http://localhost/invite", "Factorio"
    )
    assert result.status == "pending"
