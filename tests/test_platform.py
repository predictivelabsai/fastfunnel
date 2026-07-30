from datetime import date
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from fastfunnel.domain.actions import ActionService
from fastfunnel.domain.analytics import AnalyticsService
from fastfunnel.domain.content import ContentService
from fastfunnel.domain.ingestion import IngestionService
from fastfunnel.domain.marketing import MarketingService
from fastfunnel.domain.store import Store, now_iso
from fastfunnel.domain.workspace import (
    APITokenPrincipal,
    APITokenService,
    SecretVault,
    WorkspaceConfiguration,
)
from fastfunnel.integrations.destinations import FastSMEDestination, GoogleSheetsDestination
from fastfunnel.integrations.execution import (
    ArcadeProvider,
    ComposioProvider,
    ToolResult,
)
from fastfunnel.integrations.sources import BrevoConnector, HubSpotConnector
from fastfunnel.skills import effective_instructions, save_overlay, skill_for_company
from fastfunnel.web.api_core import Resource, SQLiteBackend


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
        "fastfunnel.domain.actions.provider_for",
        lambda _provider, **_kwargs: FakeProvider(),
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
        [{"session_id": "session-1"}, {"data": {"id": "post-1"}}]
    )
    result = ComposioProvider(composio_transport).execute(
        external_user_id="tenant-user",
        tool="LINKEDIN_CREATE_POST",
        arguments={"text": "Hello"},
        connected_account_id="account-1",
    )
    assert result.status == "succeeded"
    assert len(composio_transport.calls) == 2
    assert composio_transport.calls[0]["url"].endswith(
        "/api/v3/tool_router/session"
    )
    assert composio_transport.calls[0]["body"] == {
        "user_id": "tenant-user",
        "toolkits": {"enabled": ["linkedin"]},
        "manage_connections": {"enable": True},
        "connected_accounts": {"linkedin": "account-1"},
    }
    assert composio_transport.calls[1]["url"].endswith(
        "/api/v3/tool_router/session/session-1/execute"
    )
    assert composio_transport.calls[1]["body"] == {
        "tool_slug": "LINKEDIN_CREATE_POST",
        "arguments": {"text": "Hello"},
    }

    monkeypatch.setenv("ARCADE_API_KEY", "arcade-test")
    arcade_transport = FakeTransport([{"id": "post-2"}])
    ArcadeProvider(arcade_transport).execute(
        external_user_id="tenant-user",
        tool="LinkedIn.CreatePost",
        arguments={"text": "Hello"},
    )
    assert arcade_transport.calls[0]["headers"] == {
        "Authorization": "Bearer arcade-test"
    }
    assert arcade_transport.calls[0]["body"] == {
        "tool_name": "LinkedIn.CreatePost",
        "input": {"text": "Hello"},
        "user_id": "tenant-user",
    }


def test_provider_keys_validate_with_read_only_calls():
    composio_transport = FakeTransport([{"items": []}])
    ComposioProvider(
        composio_transport,
        api_key="composio-project-key",
    ).validate_api_key()
    assert composio_transport.calls[0] == {
        "method": "GET",
        "url": "https://backend.composio.dev/api/v3/toolkits?limit=1",
        "headers": {"x-api-key": "composio-project-key"},
        "body": None,
    }

    arcade_transport = FakeTransport([{"items": []}])
    ArcadeProvider(
        arcade_transport,
        api_key="arcade-project-key",
    ).validate_api_key()
    assert arcade_transport.calls[0] == {
        "method": "GET",
        "url": "https://api.arcade.dev/v1/tools",
        "headers": {"Authorization": "Bearer arcade-project-key"},
        "body": None,
    }


def test_workspace_model_settings_and_encrypted_provider_keys(
    tmp_path: Path,
    monkeypatch,
):
    store = Store(tmp_path / "workspace.sqlite3")
    store.initialize()
    company_id = store.default_company_id()
    configuration = WorkspaceConfiguration(store)

    preferences = configuration.save_model_preferences(
        company_id=company_id,
        actor_id="usr_admin",
        provider="xai",
        model="grok-4-fast",
        temperature=0.4,
    )
    assert preferences.model == "grok-4-fast"
    assert preferences.temperature == 0.4

    encryption_key = Fernet.generate_key().decode()
    monkeypatch.setenv("FASTFUNNEL_ENCRYPTION_KEY", encryption_key)
    vault = SecretVault(store)
    status = vault.save_provider_key(
        company_id=company_id,
        actor_id="usr_admin",
        provider="composio",
        api_key="cmp_test_secret_12345",
    )
    assert status["status"] == "validated"
    assert status["fingerprint"]
    assert "cmp_test_secret_12345" not in str(status)
    assert vault.provider_key(company_id, "composio") == "cmp_test_secret_12345"
    with store.connect() as conn:
        stored = conn.execute(
            "SELECT ciphertext FROM integration_secrets WHERE company_id=?",
            (company_id,),
        ).fetchone()["ciphertext"]
        audit = conn.execute(
            """SELECT details_json FROM audit_events
               WHERE event_type='integration.credential.updated'"""
        ).fetchone()["details_json"]
    assert b"cmp_test_secret_12345" not in stored
    assert "cmp_test_secret_12345" not in audit

    vault.delete_provider_key(
        company_id=company_id,
        actor_id="usr_admin",
        provider="composio",
    )
    assert vault.provider_key(company_id, "composio") is None


def test_workspace_api_tokens_are_hashed_tenant_bound_and_revocable(
    tmp_path: Path,
):
    store = Store(tmp_path / "api-tokens.sqlite3")
    store.initialize()
    company_id = store.default_company_id()
    service = APITokenService(store)

    raw_token, metadata = service.issue(
        company_id=company_id,
        actor_id="usr_admin",
        label="FastInsights production",
        lifetime_days=30,
    )
    assert raw_token.startswith("ff_live_")
    assert raw_token not in str(metadata)
    assert raw_token not in str(service.list(company_id))
    principal = service.authenticate(raw_token)
    assert principal.company_id == company_id
    assert principal.actor_id == "usr_admin"
    with store.connect() as conn:
        stored = conn.execute(
            "SELECT token_hash FROM api_tokens WHERE id=?",
            (metadata["id"],),
        ).fetchone()["token_hash"]
    assert stored != raw_token

    service.revoke(
        company_id=company_id,
        actor_id="usr_admin",
        token_id=metadata["id"],
    )
    assert service.authenticate(raw_token) is None

    other_company, _ = store.ensure_user_workspace("other.api@example.test")
    backend = SQLiteBackend(
        store.path,
        (
            Resource(
                "campaigns",
                "campaigns",
                "Campaigns",
                "Tenant campaigns",
            ),
        ),
    )
    rows, total = backend.list(
        backend.resources["campaigns"],
        limit=200,
        offset=0,
        query=None,
        company_id=company_id,
    )
    assert rows and total == len(rows)
    assert {row["company_id"] for row in rows} == {company_id}
    assert other_company["id"] not in {row["company_id"] for row in rows}


def test_content_generation_uses_configured_model_gateway(tmp_path: Path):
    store = Store(tmp_path / "content-model.sqlite3")
    store.initialize()
    company_id = store.default_company_id()

    class FakeGateway:
        def invoke(self, **kwargs):
            assert kwargs["company_id"] == company_id
            assert kwargs["messages"][1][0] == "human"
            return "A grounded model-generated post."

    item_id = ContentService(store, FakeGateway()).create_draft(
        company_id=company_id,
        actor_id="usr_admin",
        goal="Explain measurable marketing",
        channel="linkedin",
    )
    item = next(
        item for item in store.list_content(company_id) if item["id"] == item_id
    )
    assert item["body"] == "A grounded model-generated post."
    assert item["status"] == "review"


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


def test_account_provisioning_seeds_an_isolated_working_product(tmp_path: Path):
    store = Store(tmp_path / "tenants.sqlite3")
    store.initialize()
    demo_company_id = store.default_company_id()

    company, user = store.ensure_user_workspace(
        "new.owner@example.test", "New Owner"
    )
    repeated_company, repeated_user = store.ensure_user_workspace(
        "NEW.OWNER@example.test", "Ignored Rename"
    )
    store.initialize()

    assert company["id"] != demo_company_id
    assert repeated_company["id"] == company["id"]
    assert repeated_user["id"] == user["id"]
    assert store.company_for_user(user["email"], company["id"])["id"] == company["id"]
    with pytest.raises(LookupError):
        store.company_for_user(user["email"], demo_company_id)

    funnel = MarketingService(store).funnel(company_id=company["id"])
    assert funnel["definition"]["company_id"] == company["id"]
    assert len(funnel["stages"]) == 6
    assert funnel["values"][0] > funnel["values"][-1] > 0
    assert AnalyticsService(store).explore(
        company_id=company["id"], metric="clicks", dimension="provider"
    )

    item_id = store.create_content(
        "Tenant calendar item",
        "This item must stay inside the new workspace.",
        "linkedin",
        company_id=company["id"],
        actor_id=user["id"],
    )
    store.approve_content(
        item_id, company_id=company["id"], reviewer_id=user["id"]
    )
    store.schedule_content(
        item_id,
        "2026-08-01T09:00:00+00:00",
        company_id=company["id"],
        actor_id=user["id"],
    )
    store.reschedule_content(
        item_id,
        "2026-08-02T10:00:00+00:00",
        company_id=company["id"],
        actor_id=user["id"],
    )
    scheduled = store.list_content(company["id"])[0]
    assert scheduled["status"] == "scheduled"
    assert scheduled["scheduled_for"] == "2026-08-02T10:00:00+00:00"
    assert not store.list_content(demo_company_id)
    assert store.dashboard(company["id"])["members"][0]["email"] == user["email"]
    assert store.company_for_user(user["email"])["name"] == "New Owner Marketing"


def test_api_reads_are_not_public():
    from fastfunnel.web.api import api

    campaigns = next(
        route for route in api.routes if getattr(route, "path", "") == "/v1/campaigns"
    )
    assert campaigns.dependant.dependencies


def test_mcp_lists_read_tools_and_proposal_only_activation():
    from fastfunnel.web.api import MCPRequest, mcp_gateway

    principal = APITokenPrincipal(
        company_id="co_predictivelabs",
        organization_id="org_predictivelabs",
        actor_id="usr_admin",
    )
    response = mcp_gateway(
        MCPRequest(id=1, method="tools/list"),
        principal,
    )
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
