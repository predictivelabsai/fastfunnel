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
    _i("meta-ads", "Meta Ads", "Advertising", "available",
       capabilities=("campaigns.read", "campaigns.write", "performance.read")),
    _i("linkedin-ads", "LinkedIn Ads", "Advertising", "available",
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
    _i("search-console", "Google Search Console", "Analytics & search", "available",
       capabilities=("search.read",)),
    _i("buffer", "Buffer", "Social publishing", "stub", ("buffer", "direct"),
       ("channels.read", "content.publish", "content.metrics.read")),
    _i("linkedin", "LinkedIn", "Social publishing", "available",
       ("arcade", "direct", "composio"), ("content.publish", "content.metrics.read")),
    _i("facebook-instagram", "Facebook / Instagram", "Social publishing", "available",
       capabilities=("content.publish", "content.metrics.read")),
    _i("threads", "Threads", "Social publishing"),
    _i("x", "X", "Social publishing", "available",
       ("arcade", "direct", "composio"), ("content.publish", "content.metrics.read")),
    _i("bluesky", "Bluesky", "Social publishing"),
    _i("mastodon", "Mastodon", "Social publishing"),
    _i("youtube", "YouTube", "Social publishing"),
    _i("pinterest", "Pinterest", "Social publishing"),
    _i("google-business", "Google Business Profile", "Social publishing"),
    _i("hubspot", "HubSpot", "CRM & revenue"),
    _i("salesforce", "Salesforce", "CRM & revenue"),
    _i("stripe", "Stripe", "CRM & revenue"),
    _i("mailchimp", "Mailchimp", "Email & CMS"),
    _i("resend", "Resend", "Email & CMS"),
    _i("wordpress", "WordPress", "Email & CMS"),
    _i("csv-parquet", "CSV / Parquet", "Data & destinations", "available",
       ("direct",), ("data.export", "data.import")),
    _i("google-sheets", "Google Sheets", "Data & destinations"),
    _i("postgres", "Postgres", "Data & destinations", "available",
       ("direct",), ("data.read", "data.write")),
    _i("bigquery", "BigQuery", "Data & destinations"),
    _i("s3", "S3-compatible storage", "Data & destinations"),
    _i("webhooks", "Webhooks", "Data & destinations"),
    _i("composio", "Composio", "Agent providers", "available",
       ("composio",), ("tools.discover", "tools.execute", "auth.delegate")),
    _i("arcade", "Arcade", "Agent providers", "available",
       ("arcade",), ("tools.execute", "auth.delegate", "mcp.gateway")),
    _i("custom-mcp", "Custom MCP server", "Agent providers"),
    _i("generic-rest", "Generic REST connector", "Developer"),
    _i("connector-sdk", "Connector SDK", "Developer"),
)

CATEGORIES = tuple(dict.fromkeys(item.category for item in INTEGRATIONS))


def all_integrations() -> tuple[Integration, ...]:
    return INTEGRATIONS


def get_integration(integration_id: str) -> Integration | None:
    return next((item for item in INTEGRATIONS if item.id == integration_id), None)
