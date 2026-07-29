"""FastFunnel public reads and policy-safe token-gated writes."""

from fastapi import Depends
from pydantic import BaseModel, Field

from fastfunnel.config import settings
from fastfunnel.domain.store import store

from .api_core import (
    Resource,
    SQLiteBackend,
    create_sqlite_api,
    require_write_token,
)

RESOURCES = (
    Resource("campaigns", "campaigns", "Campaigns", "Synced campaign records and delivery state.", search_fields=("name", "channel", "status", "provider")),
    Resource("content", "content_items", "Content", "Content drafts, review state, and scheduling metadata.", search_fields=("title", "body", "channel", "status")),
    Resource("analytics", "marketing_facts", "Analytics", "Date-grained campaign and channel marketing facts.", search_fields=("provider", "metric", "fact_date")),
    Resource("journeys", "journey_entities", "Journey events", "Synthetic customer journey progression events.", search_fields=("source", "occurred_on")),
)

backend = SQLiteBackend(settings.database_path, RESOURCES, initialize=store.initialize)
api = create_sqlite_api(
    product="FastFunnel", version="1.0.0",
    description="Open integration access to FastFunnel campaigns, content, analytics, and journeys.",
    base_url="https://funnel.fastsme.com", backend=backend, resources=RESOURCES,
)


class ContentDraft(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    channel: str = Field(examples=["linkedin"])


@api.post(
    "/v1/content",
    status_code=201,
    dependencies=[Depends(require_write_token)],
    tags=["Content"],
)
def create_content_draft(payload: ContentDraft):
    """Create content in review state through FastFunnel's audited policy path."""

    item_id = store.create_content(payload.title, payload.body, payload.channel)
    return backend.get(RESOURCES[1], item_id)
