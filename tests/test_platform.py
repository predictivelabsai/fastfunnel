from datetime import date
from pathlib import Path

import pytest

from fastfunnel.domain.actions import ActionService
from fastfunnel.domain.analytics import AnalyticsService
from fastfunnel.domain.ingestion import IngestionService
from fastfunnel.domain.store import Store, now_iso
from fastfunnel.integrations.destinations import FastSMEDestination, GoogleSheetsDestination
from fastfunnel.integrations.execution import (
    ArcadeProvider,
    ComposioProvider,
    ToolResult,
)
from fastfunnel.integrations.sources import BrevoConnector, HubSpotConnector
from fastfunnel.skills import effective_instructions, save_overlay, skill_for_company


class FakeTransport:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def request(self, method, url, *, headers=None, body=None):
        self.calls.append(
            {"method": method, "url": url, "headers": headers or {}, "body": body}
        )
        return self.responses.pop(0) if self.responses else {"id": "receipt-1"}


def test_hubspot_and_brevo_ingestion_retains_raw_and_normalizes(tmp_path: Path):
    store = Store(tmp_path / "sources.sqlite3")
    store.initialize()
    service = IngestionService(store)
    company_id = store.default_company_id()

    hubspot = service.sync(HubSpotConnector("synthetic"), company_id=company_id)
    brevo = service.sync(BrevoConnector("synthetic"), company_id=company_id)

    assert hubspot["rows"] == 4
    assert brevo["rows"] == 2
    with store.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM raw_extracts WHERE company_id=?", (company_id,)
        ).fetchone()[0] >= 7
        assert conn.execute(
            "SELECT COUNT(*) FROM crm_entities WHERE company_id=?", (company_id,)
        ).fetchone()[0] >= 5
        assert conn.execute(
            """SELECT COUNT(*) FROM marketing_facts
               WHERE company_id=? AND provider='brevo'""",
            (company_id,),
        ).fetchone()[0] == 4


def test_live_connector_contracts_use_injected_transport(monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    transport = FakeTransport(
        [
            {
                "results": [
                    {
                        "id": "123",
                        "updatedAt": "2026-07-29T10:00:00Z",
                        "properties": {"email": "lead@example.test", "lifecyclestage": "lead"},
                    }
                ]
            }
        ]
    )
    batch = HubSpotConnector("live", transport).fetch(
        date(2026, 7, 1),
        date(2026, 7, 29),
    )
    assert batch.records[0].external_id == "123"
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer test-token"


def test_editable_skill_overlay_never_modifies_upstream(tmp_path: Path):
    store = Store(tmp_path / "skills.sqlite3")
    store.initialize()
    company_id = store.default_company_id()
    upstream_skill = skill_for_company(store, company_id, "social")
    upstream_before = upstream_skill.path.read_text()

    customized = save_overlay(
        store,
        company_id,
        "social",
        "Use a precise, evidence-led voice. Never publish without approval.",
        enabled=True,
        actor_id="usr_admin",
    )

    assert customized.status == "customized"
    assert customized.version == 1
    assert "evidence-led" in effective_instructions(customized, {"brand": "Predictive Labs"})
    assert upstream_skill.path.read_text() == upstream_before


def test_action_execution_is_payload_bound_idempotent_and_audited(
    tmp_path: Path, monkeypatch
):
    store = Store(tmp_path / "actions.sqlite3")
    store.initialize()
    company_id = store.default_company_id()
    service = ActionService(store)
    with store.connect() as conn:
        conn.execute(
            """INSERT INTO provider_identities
               (id, company_id, user_id, provider, external_user_id,
                connected_account_id, status, created_at, updated_at)
               VALUES ('pid_1', ?, 'usr_admin', 'arcade', 'tenant-user-1',
                       'account-1', 'connected', ?, ?)""",
            (company_id, now_iso(), now_iso()),
        )
    request = service.propose(
        company_id=company_id,
        actor_id="usr_admin",
        action_type="content.publish",
        provider="arcade",
        object_type="content",
        object_id=None,
        payload={"tool": "LinkedIn.CreatePost", "text": "Approved exact revision"},
        idempotency_key="publish:revision-1",
    )
    assert service.propose(
        company_id=company_id,
        actor_id="usr_admin",
        action_type="content.publish",
        provider="arcade",
        object_type="content",
        object_id=None,
        payload={"tool": "LinkedIn.CreatePost", "text": "Approved exact revision"},
        idempotency_key="publish:revision-1",
    )["id"] == request["id"]
    with pytest.raises(ValueError):
        service.propose(
            company_id=company_id,
            actor_id="usr_admin",
            action_type="content.publish",
            provider="arcade",
            object_type="content",
            object_id=None,
            payload={"tool": "LinkedIn.CreatePost", "text": "Changed after approval"},
            idempotency_key="publish:revision-1",
        )
    service.approve(request["id"], reviewer_id="usr_admin")

    class FakeProvider:
        def execute(self, **_kwargs):
            return ToolResult("arcade", "LinkedIn.CreatePost", "succeeded", {"id": "post-1"})

    monkeypatch.setattr(
        "fastfunnel.domain.actions.provider_for", lambda _provider: FakeProvider()
    )
    assert service.execute(request["id"]) == {"id": "post-1"}
    assert service.execute(request["id"]) == {"id": "post-1"}
    with store.connect() as conn:
        assert conn.execute(
            """SELECT COUNT(*) FROM action_executions
               WHERE action_request_id=? AND status='succeeded'""",
            (request["id"],),
        ).fetchone()[0] == 1


def test_composio_and_arcade_provider_contracts(monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "composio-test")
    composio_transport = FakeTransport(
        [{"id": "session-1"}, {"data": {"id": "post-1"}}]
    )
    result = ComposioProvider(composio_transport).execute(
        external_user_id="tenant-user",
        tool="LINKEDIN_CREATE_POST",
        arguments={"text": "Hello"},
    )
    assert result.status == "succeeded"
    assert len(composio_transport.calls) == 2

    monkeypatch.setenv("ARCADE_API_KEY", "arcade-test")
    arcade_transport = FakeTransport([{"id": "post-2"}])
    ArcadeProvider(arcade_transport).execute(
        external_user_id="tenant-user",
        tool="LinkedIn.CreatePost",
        arguments={"text": "Hello"},
    )
    assert arcade_transport.calls[0]["headers"]["Arcade-User-ID"] == "tenant-user"


def test_google_sheets_and_fastsme_destination_contracts(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_ACCESS_TOKEN", "sheets-test")
    sheets_transport = FakeTransport([{"updatedRows": 2}])
    receipt = GoogleSheetsDestination(sheets_transport).export(
        [{"campaign": "Search", "clicks": 12}, {"campaign": "Social", "clicks": 8}],
        {"spreadsheet_id": "sheet-1", "range": "FastFunnel!A1"},
    )
    assert receipt.rows_written == 2
    assert sheets_transport.calls[0]["method"] == "PUT"

    monkeypatch.setenv("FASTSME_API_TOKEN", "fastsme-test")
    fastsme_transport = FakeTransport([{"id": "dashboard-1"}])
    receipt = FastSMEDestination(fastsme_transport).export(
        [{"title": "Marketing KPI dashboard", "description": "FastFunnel export"}],
        {"base_url": "https://insights.fastsme.com", "resource": "dashboards"},
    )
    assert receipt.rows_written == 1
    with pytest.raises(ValueError):
        FastSMEDestination(fastsme_transport).export(
            [{"title": "No"}],
            {"base_url": "https://untrusted.example", "resource": "dashboards"},
        )


def test_kpi_explorer_is_allow_listed_and_tenant_scoped(tmp_path: Path):
    store = Store(tmp_path / "analytics.sqlite3")
    store.initialize()
    company_id = store.default_company_id()
    analytics = AnalyticsService(store)
    assert {item["slug"] for item in analytics.kpis(company_id)} >= {"ctr", "cpc"}
    assert analytics.explore(
        company_id=company_id, metric="clicks", dimension="provider"
    )
    with pytest.raises(ValueError):
        analytics.explore(
            company_id=company_id,
            metric="clicks); DROP TABLE users;--",
            dimension="provider",
        )


def test_api_reads_are_not_public():
    from fastfunnel.web.api import api

    campaigns = next(
        route for route in api.routes if getattr(route, "path", "") == "/v1/campaigns"
    )
    assert campaigns.dependant.dependencies


def test_mcp_lists_read_tools_and_proposal_only_activation():
    from fastfunnel.web.api import MCPRequest, mcp_gateway

    response = mcp_gateway(MCPRequest(id=1, method="tools/list"))
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert names == {
        "fastfunnel_kpis",
        "fastfunnel_funnel",
        "fastfunnel_propose_activation",
    }
    activation = next(
        tool
        for tool in response["result"]["tools"]
        if tool["name"] == "fastfunnel_propose_activation"
    )
    assert "propose" in activation["description"].lower() or "approval" in activation[
        "description"
    ].lower()
