"""Configurable LangChain model boundary for tenant-grounded generation."""

from __future__ import annotations

import os
from collections.abc import Sequence

from langchain_xai import ChatXAI

from fastfunnel.domain.store import Store
from fastfunnel.domain.workspace import WorkspaceConfiguration


class ModelGateway:
    def __init__(self, store: Store):
        self.store = store

    def readiness(self, company_id: str) -> tuple[str, str]:
        preferences = WorkspaceConfiguration(self.store).model_preferences(company_id)
        if preferences.provider == "xai" and os.getenv("XAI_API_KEY"):
            return "connected", f"xAI · {preferences.model}"
        return "not_configured", "XAI_API_KEY is not configured for this deployment"

    def invoke(
        self,
        *,
        company_id: str,
        messages: Sequence[tuple[str, str]],
    ) -> str:
        preferences = WorkspaceConfiguration(self.store).model_preferences(company_id)
        if preferences.provider != "xai":
            raise RuntimeError(f"Unsupported model provider: {preferences.provider}")
        if not os.getenv("XAI_API_KEY"):
            raise RuntimeError("xAI is not configured")
        model = ChatXAI(
            model=preferences.model,
            temperature=preferences.temperature,
            max_retries=2,
            timeout=45,
        )
        response = model.invoke(list(messages))
        content = response.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "\n".join(
                str(part.get("text", part)) if isinstance(part, dict) else str(part)
                for part in content
            ).strip()
        return str(content).strip()
