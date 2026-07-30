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

    def __init__(
        self,
        transport: JSONTransport | None = None,
        api_key: str | None = None,
    ):
        self.transport = transport or UrllibJSONTransport()
        self.api_key = api_key

    def readiness(self) -> tuple[str, str]:
        if not self._key():
            return "available", f"Adapter implemented; set {self.api_key_env} to connect"
        return "connected", "API key configured"

    def _key(self) -> str:
        return (self.api_key or os.getenv(self.api_key_env, "")).strip()

    def validate_api_key(self) -> None:
        """Perform a read-only provider request before accepting a credential."""
        raise NotImplementedError

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

    def validate_api_key(self) -> None:
        key = self._key()
        if not key:
            raise ValueError("Composio API key is required")
        base = os.getenv("COMPOSIO_API_BASE", "https://backend.composio.dev/api/v3")
        self.transport.request(
            "GET",
            f"{base.rstrip('/')}/toolkits?limit=1",
            headers={"x-api-key": key},
        )

    def execute(
        self,
        *,
        external_user_id: str,
        tool: str,
        arguments: dict[str, Any],
        connected_account_id: str | None = None,
    ) -> ToolResult:
        key = self._key()
        if not key:
            raise RuntimeError("Composio API key is not configured")
        base = os.getenv("COMPOSIO_API_BASE", "https://backend.composio.dev/api/v3")
        toolkit = tool.split("_", 1)[0].lower()
        session_body: dict[str, Any] = {
            "user_id": external_user_id,
            "toolkits": {"enabled": [toolkit]},
            "manage_connections": {"enable": True},
        }
        if connected_account_id:
            session_body["connected_accounts"] = {
                toolkit: connected_account_id,
            }
        session = self.transport.request(
            "POST",
            f"{base.rstrip('/')}/tool_router/session",
            headers={"x-api-key": key},
            body=session_body,
        )
        session_id = session.get("session_id")
        if not session_id:
            raise RuntimeError("Composio did not return a session id")
        receipt = self.transport.request(
            "POST",
            f"{base.rstrip('/')}/tool_router/session/{session_id}/execute",
            headers={"x-api-key": key},
            body={"tool_slug": tool, "arguments": arguments},
        )
        return ToolResult(self.provider, tool, "succeeded", receipt)


class ArcadeProvider(ExecutionProvider):
    provider = "arcade"
    api_key_env = "ARCADE_API_KEY"

    def validate_api_key(self) -> None:
        key = self._key()
        if not key:
            raise ValueError("Arcade API key is required")
        base = os.getenv("ARCADE_API_BASE", "https://api.arcade.dev/v1")
        self.transport.request(
            "GET",
            f"{base.rstrip('/')}/tools",
            headers={"Authorization": f"Bearer {key}"},
        )

    def execute(
        self,
        *,
        external_user_id: str,
        tool: str,
        arguments: dict[str, Any],
        connected_account_id: str | None = None,
    ) -> ToolResult:
        key = self._key()
        if not key:
            raise RuntimeError("Arcade API key is not configured")
        base = os.getenv("ARCADE_API_BASE", "https://api.arcade.dev/v1")
        receipt = self.transport.request(
            "POST",
            f"{base.rstrip('/')}/tools/execute",
            headers={"Authorization": f"Bearer {key}"},
            body={
                "tool_name": tool,
                "input": arguments,
                "user_id": external_user_id,
            },
        )
        return ToolResult(self.provider, tool, "succeeded", receipt)


def provider_for(
    name: str,
    transport: JSONTransport | None = None,
    api_key: str | None = None,
) -> ExecutionProvider:
    providers = {
        "composio": ComposioProvider,
        "arcade": ArcadeProvider,
    }
    try:
        return providers[name](transport, api_key)
    except KeyError as exc:
        raise LookupError(f"Unsupported execution provider: {name}") from exc
