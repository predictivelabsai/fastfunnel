"""Opt-in read-only validation for real delegated-provider credentials.

Run explicitly with:
    RUN_LIVE_INTEGRATION_TESTS=1 uv run pytest -q tests/test_live_integrations.py

The repository's ignored `.env` is loaded only for this opt-in suite. These
tests list provider tools/toolkits and never execute a tool or expose a key.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.error import HTTPError

import pytest
from dotenv import load_dotenv

from fastfunnel.integrations.execution import ArcadeProvider, ComposioProvider

ROOT = Path(__file__).resolve().parents[1]
LIVE_FLAG = "RUN_LIVE_INTEGRATION_TESTS"

pytestmark = pytest.mark.live_integration


def _provider(provider_type):
    if os.getenv(LIVE_FLAG) != "1":
        pytest.skip(f"set {LIVE_FLAG}=1 to run read-only provider validation")
    load_dotenv(ROOT / ".env", override=False)
    provider = provider_type()
    status, reason = provider.readiness()
    assert status == "connected", reason
    return provider


def _validate(provider_type) -> None:
    provider = _provider(provider_type)
    rejected_status = None
    try:
        provider.validate_api_key()
    except HTTPError as exc:
        rejected_status = exc.code
    if rejected_status is not None:
        pytest.fail(
            f"{provider.provider} rejected the configured credential "
            f"(HTTP {rejected_status})",
            pytrace=False,
        )


def test_composio_api_key_is_valid():
    """A valid key can list one Composio toolkit through the v3 API."""
    _validate(ComposioProvider)


def test_arcade_api_key_is_valid():
    """A valid key can list Arcade tools through the v1 API."""
    _validate(ArcadeProvider)
