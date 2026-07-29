"""Delegated tool execution adapters for Composio and Arcade."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from fastfunnel.integrations.sources import JSONTransport, UrllibJSONTransport


@dataclass(frozen=True)
class ToolResult:
    provider: str
    tool: str
    status: str
    receipt: dict[str, Any]


class ExecutionProvider:
    provider: str
    api_key_env: str

    def __init__(self, transport: JSONTransport | None = None):
        self.transport = transport or UrllibJSONTransport()

    def readiness(self) -> tuple[str, str]:
        if not os.getenv(self.api_key_env):
            return "available", f"Adapter implemented; set {self.api_key_env} to connect"
        return "connected", "API key configured"

    def execute(
        self,
        *,
        external_user_id: str,
        tool: str,
        arguments: dict[str, Any],
        connected_account_id: str | None = None,
    ) -> ToolResult:
        raise NotImplementedError


class ComposioProvider(ExecutionProvider):
    """Composio session tool execution.

    Endpoint paths remain configurable so hosted and regional deployments can
    be selected without changing domain code.
    """

    provider = "composio"
    api_key_env = "COMPOSIO_API_KEY"

    def execute(
        self,
        *,
        external_user_id: str,
        tool: str,
        arguments: dict[str, Any],
        connected_account_id: str | None = None,
    ) -> ToolResult:
        key = os.environ[self.api_key_env]
        base = os.getenv("COMPOSIO_API_BASE", "https://backend.composio.dev/api/v3")
        session = self.transport.request(
            "POST",
            f"{base.rstrip('/')}/sessions",
            headers={"x-api-key": key},
            body={
                "user_id": external_user_id,
                "toolkits": [tool.split("_", 1)[0].lower()],
                "manage_connections": True,
            },
        )
        session_id = session.get("id") or session.get("session_id")
        if not session_id:
            raise RuntimeError("Composio did not return a session id")
        payload: dict[str, Any] = {"tool": tool, "arguments": arguments}
        if connected_account_id:
            payload["connected_account_id"] = connected_account_id
        receipt = self.transport.request(
            "POST",
            f"{base.rstrip('/')}/sessions/{session_id}/execute",
            headers={"x-api-key": key},
            body=payload,
        )
        return ToolResult(self.provider, tool, "succeeded", receipt)


class ArcadeProvider(ExecutionProvider):
    provider = "arcade"
    api_key_env = "ARCADE_API_KEY"

    def execute(
        self,
        *,
        external_user_id: str,
        tool: str,
        arguments: dict[str, Any],
        connected_account_id: str | None = None,
    ) -> ToolResult:
        key = os.environ[self.api_key_env]
        base = os.getenv("ARCADE_API_BASE", "https://api.arcade.dev/v1")
        receipt = self.transport.request(
            "POST",
            f"{base.rstrip('/')}/tools/execute",
            headers={"Authorization": f"Bearer {key}", "Arcade-User-ID": external_user_id},
            body={
                "tool_name": tool,
                "input": arguments,
                **(
                    {"connected_account_id": connected_account_id}
                    if connected_account_id
                    else {}
                ),
            },
        )
        return ToolResult(self.provider, tool, "succeeded", receipt)


def provider_for(name: str, transport: JSONTransport | None = None) -> ExecutionProvider:
    providers = {
        "composio": ComposioProvider,
        "arcade": ArcadeProvider,
    }
    try:
        return providers[name](transport)
    except KeyError as exc:
        raise LookupError(f"Unsupported execution provider: {name}") from exc
