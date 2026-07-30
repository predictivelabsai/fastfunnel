"""FastFunnel tenant reads, policy-safe writes, and an MCP-compatible gateway."""

import json
from typing import Any

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from fastfunnel.config import settings
from fastfunnel.domain.actions import ActionService
from fastfunnel.domain.analytics import AnalyticsService
from fastfunnel.domain.marketing import MarketingService
from fastfunnel.domain.store import store
from fastfunnel.domain.workspace import (
    APITokenPrincipal,
    APITokenService,
)

from .api_core import (
    Resource,
    SQLiteBackend,
    bearer,
    create_sqlite_api,
)

RESOURCES = (
    Resource("campaigns", "campaigns", "Campaigns", "Synced campaign records and delivery state.", search_fields=("name", "channel", "status", "provider")),
    Resource("content", "content_items", "Content", "Content drafts, review state, and scheduling metadata.", search_fields=("title", "body", "channel", "status")),
    Resource("analytics", "marketing_facts", "Analytics", "Date-grained campaign and channel marketing facts.", search_fields=("provider", "metric", "fact_date")),
    Resource("journeys", "journey_entities", "Journey events", "Synthetic customer journey progression events.", search_fields=("source", "occurred_on")),
    Resource("crm", "crm_entities", "CRM entities", "HubSpot and Brevo lifecycle and revenue entities.", search_fields=("provider", "entity_type", "lifecycle_stage")),
    Resource("sources", "data_sources", "Data sources", "Tenant-scoped source configurations and health.", search_fields=("provider", "name", "status")),
    Resource("sync-runs", "sync_runs", "Sync runs", "Connector synchronization history and receipts.", search_fields=("provider", "status")),
    Resource("kpis", "kpi_definitions", "KPI definitions", "Reusable governed KPI definitions.", search_fields=("slug", "name", "format")),
    Resource("saved-queries", "saved_queries", "Saved queries", "Field-aware saved explorer queries.", search_fields=("name",)),
    Resource("exports", "export_runs", "Export runs", "Destination export delivery status and receipts.", search_fields=("status",)),
)

backend = SQLiteBackend(settings.database_path, RESOURCES, initialize=store.initialize)


def tenant_principal(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer),  # noqa: B008
) -> APITokenPrincipal:
    supplied = credentials.credentials if credentials else ""
    principal = APITokenService(store).authenticate(supplied) if supplied else None
    if not principal:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_token",
                "message": "A valid workspace API token is required.",
                "details": {},
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


api = create_sqlite_api(
    product="FastFunnel", version="1.0.0",
    description="Tenant-protected integration access to campaigns, content, analytics, and journeys.",
    base_url="https://funnel.fastsme.com", backend=backend, resources=RESOURCES,
    public_reads=False,
    principal_dependency=tenant_principal,
)


class ContentDraft(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    channel: str = Field(examples=["linkedin"])


@api.post(
    "/v1/content",
    status_code=201,
    tags=["Content"],
)
def create_content_draft(
    payload: ContentDraft,
    principal: APITokenPrincipal = Depends(tenant_principal),  # noqa: B008
):
    """Create content in review state through FastFunnel's audited policy path."""

    item_id = store.create_content(
        payload.title,
        payload.body,
        payload.channel,
        company_id=principal.company_id,
        actor_id=principal.actor_id,
    )
    return backend.get(
        RESOURCES[1],
        item_id,
        company_id=principal.company_id,
    )


class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


MCP_TOOLS = (
    {
        "name": "fastfunnel_kpis",
        "description": "Read governed KPI values for one company workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "fastfunnel_funnel",
        "description": "Read the configured digital acquisition funnel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 90},
            },
        },
    },
    {
        "name": "fastfunnel_propose_activation",
        "description": (
            "Create an approval request for content publication, conversion upload, "
            "or audience sync. This tool never calls a provider directly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["content.publish", "conversion.upload", "audience.sync"],
                },
                "provider": {"type": "string", "enum": ["composio", "arcade"]},
                "object_type": {"type": "string"},
                "object_id": {"type": "string"},
                "payload": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": [
                "action_type",
                "provider",
                "object_type",
                "payload",
                "idempotency_key",
            ],
        },
    },
)


@api.post(
    "/mcp",
    tags=["MCP"],
)
def mcp_gateway(
    request: MCPRequest,
    principal: APITokenPrincipal = Depends(tenant_principal),  # noqa: B008
):
    """Small Streamable-HTTP-compatible JSON-RPC surface for governed agents."""
    if request.method == "initialize":
        result = {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "FastFunnel", "version": "1.0.0"},
        }
    elif request.method == "tools/list":
        result = {"tools": list(MCP_TOOLS)}
    elif request.method == "tools/call":
        name = request.params.get("name")
        arguments = request.params.get("arguments", {})
        if name == "fastfunnel_kpis":
            data = AnalyticsService(store).kpis(principal.company_id)
        elif name == "fastfunnel_funnel":
            funnel = MarketingService(store).funnel(
                company_id=principal.company_id,
                days=int(arguments.get("days", 30)),
            )
            data = {
                "definition": funnel["definition"],
                "values": funnel["values"],
                "step_conversion": funnel["step_conversion"],
                "overall_conversion": funnel["overall_conversion"],
            }
        elif name == "fastfunnel_propose_activation":
            data = ActionService(store).propose(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                action_type=arguments["action_type"],
                provider=arguments["provider"],
                object_type=arguments["object_type"],
                object_id=arguments.get("object_id"),
                payload=arguments["payload"],
                idempotency_key=arguments["idempotency_key"],
            )
        else:
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": {"code": -32602, "message": "Unknown or invalid tool"},
            }
        result = {
            "content": [
                {"type": "text", "text": json.dumps(data, default=str)}
            ],
            "structuredContent": data,
            "isError": False,
        }
    else:
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "error": {"code": -32601, "message": "Method not found"},
        }
    return {"jsonrpc": "2.0", "id": request.id, "result": result}
