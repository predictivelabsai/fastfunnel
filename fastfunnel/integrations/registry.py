from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Integration:
    id: str
    name: str
    category: str
    status: str
    routes: tuple[str, ...]
    capabilities: tuple[str, ...]
    description: str


def _i(
    id: str,
    name: str,
    category: str,
    status: str = "stub",
    routes: tuple[str, ...] = ("direct", "composio", "custom_mcp"),
    capabilities: tuple[str, ...] = ("planned",),
    description: str = "Connector manifest is ready; implementation is planned.",
) -> Integration:
    return Integration(id, name, category, status, routes, capabilities, description)


INTEGRATIONS = (
    _i(
        "google-ads",
        "Google Ads",
        "Advertising",
        "available",
        capabilities=("campaigns.read", "performance.read"),
        description="Executable synthetic reporting adapter; live credentials are not configured.",
    ),
    _i("meta-ads", "Meta Ads", "Advertising", "stub",
       capabilities=("campaigns.read", "campaigns.write", "performance.read")),
    _i("linkedin-ads", "LinkedIn Ads", "Advertising", "stub",
       capabilities=("campaigns.read", "performance.read")),
    _i("microsoft-ads", "Microsoft Ads", "Advertising"),
    _i("tiktok-ads", "TikTok Ads", "Advertising"),
    _i(
        "ga4",
        "Google Analytics 4",
        "Analytics & search",
        "stub",
        capabilities=("analytics.read",),
        description="Read contract is defined; credentials and live transport are pending.",
    ),
    _i("search-console", "Google Search Console", "Analytics & search", "stub",
       capabilities=("search.read",)),
    _i("buffer", "Buffer", "Social publishing", "stub", ("buffer", "direct"),
       ("channels.read", "content.publish", "content.metrics.read")),
    _i("linkedin", "LinkedIn", "Social publishing", "stub",
       ("arcade", "direct", "composio"), ("content.publish", "content.metrics.read")),
    _i("facebook-instagram", "Facebook / Instagram", "Social publishing", "stub",
       capabilities=("content.publish", "content.metrics.read")),
    _i("threads", "Threads", "Social publishing"),
    _i("x", "X", "Social publishing", "stub",
       ("arcade", "direct", "composio"), ("content.publish", "content.metrics.read")),
    _i("bluesky", "Bluesky", "Social publishing"),
    _i("mastodon", "Mastodon", "Social publishing"),
    _i("youtube", "YouTube", "Social publishing"),
    _i("pinterest", "Pinterest", "Social publishing"),
    _i("google-business", "Google Business Profile", "Social publishing"),
    _i(
        "hubspot",
        "HubSpot",
        "CRM & revenue",
        "available",
        capabilities=("contacts.read", "lifecycle.read", "revenue.read"),
        description="Synthetic and live private-app read adapters with raw extract retention.",
    ),
    _i("salesforce", "Salesforce", "CRM & revenue"),
    _i(
        "stripe",
        "Stripe",
        "CRM & revenue",
        "stub",
        ("direct", "composio"),
        ("customers.read", "subscriptions.read", "payments.read"),
        "Coming soon: contract and synthetic fixtures only; no Stripe API calls are enabled.",
    ),
    _i("mailchimp", "Mailchimp", "Email & CMS"),
    _i(
        "brevo",
        "Brevo",
        "Email & CMS",
        "available",
        capabilities=("campaigns.read", "contacts.read", "performance.read"),
        description="Synthetic and live API-key read adapters with KPI normalization.",
    ),
    _i("resend", "Resend", "Email & CMS"),
    _i("wordpress", "WordPress", "Email & CMS"),
    _i("csv-parquet", "CSV / Parquet", "Data & destinations", "stub",
       ("direct",), ("data.export", "data.import")),
    _i(
        "google-sheets",
        "Google Sheets",
        "Data & destinations",
        "available",
        ("direct", "composio"),
        ("data.export",),
        "Google Sheets Values API export adapter; OAuth token required for live writes.",
    ),
    _i(
        "postgres",
        "PostgreSQL",
        "Data & destinations",
        "available",
        ("direct",),
        ("schema.inspect", "data.read"),
        "Encrypted multi-connection setup with forced read-only schema discovery.",
    ),
    _i(
        "fastsme",
        "FastSheets / FastInsights",
        "Data & destinations",
        "available",
        ("direct",),
        ("data.export", "dashboard.create", "workbook.create"),
        "Allow-listed token-gated adapter for the FastSheets and FastInsights APIs.",
    ),
    _i(
        "fastoffice",
        "FastOffice",
        "Data & destinations",
        "stub",
        ("direct",),
        ("workspace.handoff",),
        "FastOffice has no token-gated artifact API yet; cross-product handoff is pending.",
    ),
    _i("bigquery", "BigQuery", "Data & destinations"),
    _i("s3", "S3-compatible storage", "Data & destinations"),
    _i("webhooks", "Webhooks", "Data & destinations"),
    _i(
        "composio",
        "Composio",
        "Agent providers",
        "available",
        ("composio",),
        ("tools.execute", "auth.delegate"),
        "Session execution adapter implemented; API key and connected account required.",
    ),
    _i(
        "arcade",
        "Arcade",
        "Agent providers",
        "available",
        ("arcade",),
        ("tools.execute", "auth.delegate", "mcp.gateway"),
        "Per-user tool execution adapter implemented; API key and authorization required.",
    ),
    _i(
        "custom-mcp",
        "FastFunnel MCP server",
        "Agent providers",
        "available",
        ("custom_mcp",),
        ("kpis.read", "funnel.read", "activation.propose"),
        "Token-gated JSON-RPC tools at /api/mcp; mutation tools create proposals only.",
    ),
    _i("generic-rest", "Generic REST connector", "Developer"),
    _i("connector-sdk", "Connector SDK", "Developer"),
)

CATEGORIES = tuple(dict.fromkeys(item.category for item in INTEGRATIONS))


def all_integrations() -> tuple[Integration, ...]:
    return INTEGRATIONS


def get_integration(integration_id: str) -> Integration | None:
    return next((item for item in INTEGRATIONS if item.id == integration_id), None)


def runtime_readiness(
    integration_id: str,
    *,
    store=None,
    company_id: str | None = None,
) -> tuple[str, str]:
    """Return executable readiness without overstating static catalog entries."""
    from fastfunnel.integrations.destinations import (
        FastSMEDestination,
        GoogleSheetsDestination,
    )
    from fastfunnel.integrations.execution import ArcadeProvider, ComposioProvider
    from fastfunnel.integrations.marketing import GA4Connector, GoogleAdsConnector
    from fastfunnel.integrations.sources import BrevoConnector, HubSpotConnector

    tenant_key = None
    if (
        store is not None
        and company_id
        and integration_id in {"composio", "arcade"}
    ):
        from fastfunnel.domain.workspace import SecretVault

        vault = SecretVault(store)
        status = vault.provider_status(company_id, integration_id)
        if status["status"] == "validated":
            tenant_key = vault.provider_key(company_id, integration_id)

    adapters = {
        "google-ads": GoogleAdsConnector("synthetic"),
        "ga4": GA4Connector(),
        "hubspot": HubSpotConnector("live"),
        "brevo": BrevoConnector("live"),
        "google-sheets": GoogleSheetsDestination(),
        "fastsme": FastSMEDestination(),
        "composio": ComposioProvider(api_key=tenant_key),
        "arcade": ArcadeProvider(api_key=tenant_key),
    }
    adapter = adapters.get(integration_id)
    if adapter:
        return adapter.readiness()
    item = get_integration(integration_id)
    return (
        (item.status, item.description)
        if item
        else ("stub", "Unknown integration")
    )
