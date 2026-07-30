import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from fastfunnel.domain.marketing import MarketingService
from fastfunnel.domain.semantic import BUSINESS_PACKS, SemanticModelService
from fastfunnel.domain.store import Store
from fastfunnel.integrations import get_integration
from fastfunnel.integrations.postgres import (
    PostgresConnectionConfig,
    PostgresConnectionService,
)


def test_three_business_packs_are_isolated_organisations(tmp_path: Path):
    store = Store(tmp_path / "tenant-packs.sqlite3")
    store.initialize()
    service = SemanticModelService(store)
    company_ids = service.seed_business_organizations("admin@fastfunnel.app")

    assert set(company_ids) == {"co_mmg", "co_fastoffice", "co_tendly"}
    with store.connect() as connection:
        rows = connection.execute(
            """SELECT companies.id, companies.organization_id
               FROM companies WHERE companies.id IN (?, ?, ?)""",
            tuple(company_ids),
        ).fetchall()
    assert len({row["organization_id"] for row in rows}) == 3
    granted = store.workspaces_for_user("admin@fastfunnel.app")
    assert set(company_ids) <= {workspace["id"] for workspace in granted}


@pytest.mark.parametrize("pack_key", tuple(BUSINESS_PACKS))
def test_business_funnels_use_ordered_distinct_subject_cohorts(
    tmp_path: Path,
    pack_key: str,
):
    store = Store(tmp_path / f"{pack_key}.sqlite3")
    store.initialize()
    semantic = SemanticModelService(store)
    semantic.seed_business_organizations("admin@fastfunnel.app")
    company_id = BUSINESS_PACKS[pack_key]["company_id"]

    result = semantic.cohort_funnel(company_id=company_id, days=30)

    assert result["calculation"] == "ordered_distinct_subject_cohort"
    assert result["values"] == sorted(result["values"], reverse=True)
    assert result["values"][0] > result["values"][-1] > 0
    predicates = []
    with store.connect() as connection:
        rows = connection.execute(
            """SELECT predicate_json FROM funnel_stages
               WHERE funnel_id=? ORDER BY position""",
            (result["definition"]["id"],),
        ).fetchall()
        predicates = [json.loads(row["predicate_json"]) for row in rows]
    assert predicates[0]["event_name"] == "sign_in"
    assert all(predicate["ordered"] for predicate in predicates)
    shared_result = MarketingService(store).funnel(company_id=company_id, days=30)
    assert shared_result["calculation"] == "ordered_distinct_subject_cohort"
    assert shared_result["values"] == result["values"]


def test_geography_suppresses_small_cohorts(tmp_path: Path):
    store = Store(tmp_path / "geo.sqlite3")
    store.initialize()
    semantic = SemanticModelService(store)
    semantic.seed_business_organizations("admin@fastfunnel.app")

    rows = semantic.geography(company_id="co_mmg", minimum_cohort=10)

    assert rows
    assert all(row["people"] >= 10 for row in rows)
    assert all(row["latitude"] is not None and row["longitude"] is not None for row in rows)


def test_attribution_exposes_first_touch_and_last_non_direct_views(tmp_path: Path):
    store = Store(tmp_path / "attribution.sqlite3")
    store.initialize()
    semantic = SemanticModelService(store)
    semantic.seed_business_organizations("admin@fastfunnel.app")

    result = semantic.attribution(company_id="co_tendly", days=30)

    assert result["default_model"] == "first_touch"
    assert result["comparison_model"] == "last_non_direct"
    assert result["conversion_event"] == "subscription_renewed"
    assert sum(row["first_touch"] for row in result["channels"]) > 0
    assert sum(row["first_touch"] for row in result["channels"]) == sum(
        row["last_non_direct"] for row in result["channels"]
    )


class StubInspector:
    def inspect(self, config, password):
        assert password == "read-only-password"
        assert config.schemas == ("analytics",)
        return {
            "read_only": True,
            "objects": [
                {
                    "table_schema": "analytics",
                    "table_name": "fastfunnel_events_v1",
                    "table_type": "VIEW",
                }
            ],
        }


def test_postgres_credentials_are_encrypted_and_connection_scoped(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("FASTFUNNEL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    store = Store(tmp_path / "postgres-source.sqlite3")
    store.initialize()
    service = PostgresConnectionService(store, inspector=StubInspector())

    result = service.save_and_verify(
        company_id="co_predictivelabs",
        actor_id="usr_admin",
        name="Analytics read model",
        config=PostgresConnectionConfig(
            host="database.example.com",
            port=5432,
            database="marketing",
            username="fastfunnel_reader",
            schemas=("analytics",),
        ),
        password="read-only-password",
    )

    assert result["status"] == "connected"
    listed = service.list("co_predictivelabs")
    assert listed[0]["config"]["username"] == "fastfunnel_reader"
    assert "password" not in listed[0]["config"]
    with store.connect() as connection:
        secret = connection.execute(
            "SELECT ciphertext FROM connection_secrets WHERE connection_id=?",
            (result["id"],),
        ).fetchone()["ciphertext"]
    assert b"read-only-password" not in secret


def test_stripe_remains_an_honest_stub():
    stripe = get_integration("stripe")
    assert stripe is not None
    assert stripe.status == "stub"
    assert "Coming soon" in stripe.description
