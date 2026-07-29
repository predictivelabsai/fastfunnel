"""Tenant-scoped source connectors with deterministic and injectable transports."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol


class JSONTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class UrllibJSONTransport:
    """Small HTTP transport kept injectable so connector tests never need credentials."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=payload, method=method, headers=headers or {})
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())


@dataclass(frozen=True)
class SourceRecord:
    object_type: str
    external_id: str
    partition_key: str
    source_updated_at: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class SourceBatch:
    provider: str
    account_external_id: str
    account_name: str
    records: tuple[SourceRecord, ...]
    next_cursor: dict[str, Any] = field(default_factory=dict)


class SourceConnector:
    provider: str
    required_env: tuple[str, ...] = ()

    def __init__(
        self,
        mode: str = "synthetic",
        transport: JSONTransport | None = None,
    ) -> None:
        self.mode = mode
        self.transport = transport or UrllibJSONTransport()

    def readiness(self) -> tuple[str, str]:
        if self.mode == "synthetic":
            return "available", "Deterministic test adapter"
        missing = [name for name in self.required_env if not os.getenv(name)]
        if missing:
            return "available", f"Live mode requires: {', '.join(missing)}"
        return "connected", "Live credentials configured"

    def fetch(
        self, start: date, end: date, cursor: dict[str, Any] | None = None
    ) -> SourceBatch:
        raise NotImplementedError


class HubSpotConnector(SourceConnector):
    provider = "hubspot"
    required_env = ("HUBSPOT_ACCESS_TOKEN",)

    def fetch(
        self, start: date, end: date, cursor: dict[str, Any] | None = None
    ) -> SourceBatch:
        if self.mode == "synthetic":
            records = tuple(
                SourceRecord(
                    "contact",
                    f"hub-contact-{index}",
                    end.isoformat(),
                    f"{end.isoformat()}T{index:02}:00:00+00:00",
                    {
                        "email": f"lead{index}@example.test",
                        "lifecyclestage": stage,
                        "hs_lead_status": "OPEN",
                        "amount": revenue,
                        "currency": "GBP",
                        "utm_source": "google",
                    },
                )
                for index, (stage, revenue) in enumerate(
                    (
                        ("lead", 0),
                        ("marketingqualifiedlead", 0),
                        ("salesqualifiedlead", 0),
                        ("customer", 4800),
                    ),
                    1,
                )
            )
            return SourceBatch(self.provider, "synthetic-portal", "HubSpot demo", records)

        token = os.environ["HUBSPOT_ACCESS_TOKEN"]
        after = str((cursor or {}).get("after", ""))
        query = {
            "limit": "100",
            "properties": "email,lifecyclestage,hs_lead_status,lastmodifieddate",
        }
        if after:
            query["after"] = after
        response = self.transport.request(
            "GET",
            "https://api.hubapi.com/crm/v3/objects/contacts?"
            + urllib.parse.urlencode(query),
            headers={"Authorization": f"Bearer {token}"},
        )
        records = tuple(
            SourceRecord(
                "contact",
                str(item["id"]),
                end.isoformat(),
                item.get("updatedAt") or datetime.now().astimezone().isoformat(),
                item.get("properties", {}),
            )
            for item in response.get("results", [])
        )
        next_after = (
            response.get("paging", {}).get("next", {}).get("after")
        )
        return SourceBatch(
            self.provider,
            os.getenv("HUBSPOT_PORTAL_ID", "connected-portal"),
            "HubSpot",
            records,
            {"after": next_after} if next_after else {},
        )


class BrevoConnector(SourceConnector):
    provider = "brevo"
    required_env = ("BREVO_API_KEY",)

    def fetch(
        self, start: date, end: date, cursor: dict[str, Any] | None = None
    ) -> SourceBatch:
        if self.mode == "synthetic":
            records = (
                SourceRecord(
                    "email_campaign",
                    "brevo-campaign-1",
                    end.isoformat(),
                    f"{end.isoformat()}T12:00:00+00:00",
                    {
                        "name": "AI platform field guide",
                        "status": "sent",
                        "sent": 3200,
                        "delivered": 3098,
                        "uniqueOpens": 1240,
                        "uniqueClicks": 386,
                        "unsubscriptions": 9,
                    },
                ),
                SourceRecord(
                    "contact",
                    "brevo-contact-1",
                    end.isoformat(),
                    f"{end.isoformat()}T11:00:00+00:00",
                    {"email": "subscriber@example.test", "attributes": {"STAGE": "lead"}},
                ),
            )
            return SourceBatch(self.provider, "synthetic-account", "Brevo demo", records)

        key = os.environ["BREVO_API_KEY"]
        offset = int((cursor or {}).get("offset", 0))
        response = self.transport.request(
            "GET",
            "https://api.brevo.com/v3/emailCampaigns?"
            + urllib.parse.urlencode(
                {"limit": 100, "offset": offset, "sort": "desc", "excludeHtmlContent": "true"}
            ),
            headers={"api-key": key, "accept": "application/json"},
        )
        campaigns = response.get("campaigns", [])
        records = tuple(
            SourceRecord(
                "email_campaign",
                str(item["id"]),
                (item.get("sentDate") or end.isoformat())[:10],
                item.get("modifiedAt") or item.get("sentDate") or datetime.now().astimezone().isoformat(),
                item,
            )
            for item in campaigns
        )
        next_cursor = {"offset": offset + len(campaigns)} if len(campaigns) == 100 else {}
        return SourceBatch(
            self.provider,
            os.getenv("BREVO_ACCOUNT_ID", "connected-account"),
            "Brevo",
            records,
            next_cursor,
        )


class GA4SourceConnector(SourceConnector):
    """GA4 Data API connector using an already-issued OAuth access token."""

    provider = "ga4"
    required_env = ("GA4_PROPERTY_ID", "GOOGLE_ANALYTICS_ACCESS_TOKEN")

    def fetch(
        self, start: date, end: date, cursor: dict[str, Any] | None = None
    ) -> SourceBatch:
        if self.mode == "synthetic":
            record = SourceRecord(
                "analytics_report",
                f"ga4-{start}-{end}",
                end.isoformat(),
                f"{end.isoformat()}T23:59:59+00:00",
                {
                    "sessions": 4860,
                    "engagedSessions": 2916,
                    "conversions": 184,
                    "sourceMedium": "google / cpc",
                },
            )
            return SourceBatch(self.provider, "synthetic-property", "GA4 demo", (record,))
        property_id = os.environ["GA4_PROPERTY_ID"]
        response = self.transport.request(
            "POST",
            f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport",
            headers={
                "Authorization": f"Bearer {os.environ['GOOGLE_ANALYTICS_ACCESS_TOKEN']}"
            },
            body={
                "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
                "dimensions": [{"name": "sessionSourceMedium"}],
                "metrics": [
                    {"name": "sessions"},
                    {"name": "engagedSessions"},
                    {"name": "conversions"},
                ],
                "limit": 100000,
            },
        )
        records = tuple(
            SourceRecord(
                "analytics_report",
                f"{end}-{index}",
                end.isoformat(),
                f"{end.isoformat()}T23:59:59+00:00",
                {"row": row, "dimensionHeaders": response.get("dimensionHeaders", []),
                 "metricHeaders": response.get("metricHeaders", [])},
            )
            for index, row in enumerate(response.get("rows", []))
        )
        return SourceBatch(self.provider, property_id, f"GA4 {property_id}", records)
