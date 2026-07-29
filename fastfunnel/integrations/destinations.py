"""Governed export adapters for Google Sheets and the FastSME product family."""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass
from typing import Any, ClassVar

from fastfunnel.integrations.sources import JSONTransport, UrllibJSONTransport


@dataclass(frozen=True)
class ExportReceipt:
    provider: str
    rows_written: int
    details: dict[str, Any]


class Destination:
    provider: str
    required_env: tuple[str, ...]

    def __init__(self, transport: JSONTransport | None = None):
        self.transport = transport or UrllibJSONTransport()

    def readiness(self) -> tuple[str, str]:
        missing = [name for name in self.required_env if not os.getenv(name)]
        if missing:
            return "available", f"Adapter implemented; configure: {', '.join(missing)}"
        return "connected", "Destination credentials configured"

    def export(self, rows: list[dict[str, Any]], config: dict[str, Any]) -> ExportReceipt:
        raise NotImplementedError


class GoogleSheetsDestination(Destination):
    provider = "google-sheets"
    required_env = ("GOOGLE_SHEETS_ACCESS_TOKEN",)

    def export(self, rows: list[dict[str, Any]], config: dict[str, Any]) -> ExportReceipt:
        if not rows:
            return ExportReceipt(self.provider, 0, {"status": "empty"})
        spreadsheet_id = config["spreadsheet_id"]
        range_name = config.get("range", "FastFunnel!A1")
        headers = list(rows[0])
        values = [headers, *[[row.get(header) for header in headers] for row in rows]]
        response = self.transport.request(
            "PUT",
            "https://sheets.googleapis.com/v4/spreadsheets/"
            f"{spreadsheet_id}/values/{urllib.parse.quote(range_name, safe='!')}"
            "?valueInputOption=RAW",
            headers={"Authorization": f"Bearer {os.environ['GOOGLE_SHEETS_ACCESS_TOKEN']}"},
            body={"majorDimension": "ROWS", "values": values},
        )
        return ExportReceipt(self.provider, len(rows), response)


class FastSMEDestination(Destination):
    """Adapter for FastSheets, FastOffice, and FastInsights token-gated APIs."""

    provider = "fastsme"
    required_env = ("FASTSME_API_TOKEN",)
    allowed_hosts: ClassVar[set[str]] = {
        "https://sheets.fastsme.com",
        "https://insights.fastsme.com",
    }

    def export(self, rows: list[dict[str, Any]], config: dict[str, Any]) -> ExportReceipt:
        base_url = config["base_url"].rstrip("/")
        if base_url not in self.allowed_hosts:
            raise ValueError("Destination host is not allow-listed")
        resource = config["resource"].strip("/")
        if "/" in resource or not resource.replace("-", "").isalnum():
            raise ValueError("Invalid destination resource")
        receipts = []
        for row in rows:
            receipts.append(
                self.transport.request(
                    "POST",
                    f"{base_url}/api/v1/{resource}",
                    headers={
                        "Authorization": f"Bearer {os.environ['FASTSME_API_TOKEN']}"
                    },
                    body=row,
                )
            )
        return ExportReceipt(
            self.provider,
            len(receipts),
            {"destination": base_url, "resource": resource, "receipts": receipts},
        )
