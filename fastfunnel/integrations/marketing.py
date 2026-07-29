"""Read-only marketing connector contracts and deterministic launch adapters."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CampaignRecord:
    external_id: str
    name: str
    channel: str
    status: str
    daily_budget: float
    currency: str


@dataclass(frozen=True)
class FactRecord:
    fact_date: str
    campaign_external_id: str
    metric: str
    value: float
    currency: str = ""


class MarketingReadConnector(ABC):
    provider: str

    @abstractmethod
    def readiness(self) -> tuple[str, str]:
        """Return an honest registry state and human-readable reason."""

    @abstractmethod
    def fetch(self, start: date, end: date) -> tuple[list[CampaignRecord], list[FactRecord]]:
        """Fetch normalized campaigns and daily facts for an inclusive window."""


class GoogleAdsConnector(MarketingReadConnector):
    """Google Ads reporting adapter.

    Synthetic mode is deliberately executable and credential-free. Live mode is
    advertised only when the required Google Ads credential set is present.
    """

    provider = "google-ads"
    required_env = (
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
    )

    def __init__(self, mode: str = "synthetic"):
        self.mode = mode

    def readiness(self) -> tuple[str, str]:
        if self.mode == "synthetic":
            return "available", "Deterministic synthetic reporting adapter"
        missing = [name for name in self.required_env if not os.getenv(name)]
        if missing:
            return "stub", f"Live reporting requires: {', '.join(missing)}"
        return "stub", "Credentials detected; live transport implementation is pending"

    def fetch(self, start: date, end: date) -> tuple[list[CampaignRecord], list[FactRecord]]:
        if self.mode != "synthetic":
            raise RuntimeError("Live Google Ads transport is not enabled yet")
        campaigns = [
            CampaignRecord(
                "gads_search_ai",
                "AI Platform Consulting · Search",
                "Paid Search",
                "ENABLED",
                95.0,
                "GBP",
            ),
            CampaignRecord(
                "gads_retargeting",
                "AI Platform Guides · Retargeting",
                "Display",
                "ENABLED",
                35.0,
                "GBP",
            ),
        ]
        facts: list[FactRecord] = []
        day = start
        while day <= end:
            ordinal = day.toordinal()
            for index, campaign in enumerate(campaigns):
                impressions = 1450 + (ordinal % 11) * 37 + index * 310
                clicks = round(impressions * (0.043 - index * 0.009))
                spend = round(clicks * (2.35 - index * 0.55), 2)
                conversions = round(clicks * (0.075 + index * 0.012))
                for metric, value, currency in (
                    ("impressions", impressions, ""),
                    ("clicks", clicks, ""),
                    ("spend", spend, "GBP"),
                    ("conversions", conversions, ""),
                ):
                    facts.append(
                        FactRecord(
                            day.isoformat(), campaign.external_id, metric, value, currency
                        )
                    )
            day = date.fromordinal(day.toordinal() + 1)
        return campaigns, facts


class GA4Connector(MarketingReadConnector):
    provider = "ga4"

    def readiness(self) -> tuple[str, str]:
        if os.getenv("GA4_PROPERTY_ID") and os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            return "available", "Credentials detected; transport implementation is pending"
        return "stub", "Waiting for GA4 property and service-account credentials"

    def fetch(self, start: date, end: date) -> tuple[list[CampaignRecord], list[FactRecord]]:
        raise RuntimeError("GA4 reporting is not connected")
