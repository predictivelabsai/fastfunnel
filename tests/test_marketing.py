import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fastfunnel import worker
from fastfunnel.domain.funnels import FunnelStage, sankey_spec
from fastfunnel.domain.marketing import MarketingService
from fastfunnel.domain.store import Store
from fastfunnel.integrations.marketing import GA4Connector, GoogleAdsConnector


def test_sankey_conserves_every_stage():
    stages = [
        FunnelStage("Impressions", "Impressions", "No click", 1000),
        FunnelStage("Clicks", "Clicks", "No engagement", 400),
        FunnelStage("Engaged", "Engaged", "No lead", 250),
        FunnelStage("Leads", "Leads", "Not qualified", 100),
        FunnelStage("Qualified", "Qualified", "Not converted", 50),
        FunnelStage("Customers", "Customers", "—", 20),
    ]
    result = sankey_spec(stages)
    links = result["trace"]["link"]
    for stage_index, stage_value in enumerate(result["values"][:-1]):
        outgoing = sum(
            value
            for source, value in zip(links["source"], links["value"])
            if source == stage_index
        )
        assert outgoing == stage_value


def test_sankey_clamps_inconsistent_cumulative_counts():
    result = sankey_spec(
        [
            FunnelStage("A", "A", "A drop", 10),
            FunnelStage("B", "B", "B drop", 12),
            FunnelStage("C", "C", "C drop", 3),
        ]
    )
    assert result["values"] == [10, 10, 3]


def test_synthetic_ingestion_is_idempotent(tmp_path: Path):
    store = Store(tmp_path / "marketing.sqlite3")
    store.initialize()
    service = MarketingService(store)
    with store.connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM marketing_facts").fetchone()[0]
    service.sync_google_ads()
    with store.connect() as conn:
        after = conn.execute("SELECT COUNT(*) FROM marketing_facts").fetchone()[0]
        successful_runs = conn.execute(
            "SELECT COUNT(*) FROM sync_runs WHERE status='succeeded'"
        ).fetchone()[0]
    assert before == after
    assert before >= 240
    assert successful_runs >= 2


def test_default_digital_funnel_is_configurable_and_conserved(tmp_path: Path):
    store = Store(tmp_path / "funnel.sqlite3")
    store.initialize()
    result = MarketingService(store).funnel()
    assert [stage.name for stage in result["stages"]] == [
        "Impressions",
        "Clicks",
        "Engaged visits",
        "Leads",
        "Qualified leads",
        "Customers",
    ]
    assert result["values"] == sorted(result["values"], reverse=True)
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            """UPDATE funnel_stages SET name='Ad clicks'
               WHERE funnel_id='fnl_digital_marketing' AND position=1"""
        )
        conn.commit()
    assert MarketingService(store).funnel()["stages"][1].name == "Ad clicks"


def test_workspace_admin_can_create_and_select_a_custom_funnel(tmp_path: Path):
    store = Store(tmp_path / "custom-funnel.sqlite3")
    store.initialize()
    company_id = store.default_company_id()
    service = MarketingService(store)
    funnel_id = service.save_funnel(
        company_id=company_id,
        actor_id="usr_admin",
        name="Content-led acquisition",
        description="From useful content to retained customer.",
        observation_window_days=60,
        stages=[
            ("Content views", "Views", "Did not engage"),
            ("Engaged visits", "Engaged", "No lead"),
            ("Leads", "Leads", "Not converted"),
            ("Customers", "Customers", "—"),
        ],
        is_default=True,
    )

    selected = service.funnel(
        funnel_id=funnel_id,
        company_id=company_id,
        days=60,
    )
    assert selected["definition"]["is_default"] == 1
    assert [stage.name for stage in selected["stages"]] == [
        "Content views",
        "Engaged visits",
        "Leads",
        "Customers",
    ]
    assert service.funnel(company_id=company_id)["definition"]["id"] == funnel_id
    assert len(service.list_funnels(company_id)) == 2


def test_connector_readiness_is_honest(monkeypatch):
    for key in GoogleAdsConnector.required_env:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("GA4_PROPERTY_ID", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    assert GoogleAdsConnector("synthetic").readiness()[0] == "available"
    assert GoogleAdsConnector("live").readiness()[0] == "stub"
    assert GA4Connector().readiness()[0] == "stub"


def test_job_enqueue_is_idempotent(tmp_path: Path):
    store = Store(tmp_path / "jobs.sqlite3")
    store.initialize()
    service = MarketingService(store)
    assert service.enqueue_sync() == service.enqueue_sync()
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM job_queue").fetchone()[0] == 1
        available = conn.execute("SELECT available_at FROM job_queue").fetchone()[0]
    assert datetime.fromisoformat(available) <= datetime.now(UTC)


def test_worker_claims_and_completes_a_durable_job(
    tmp_path: Path,
    monkeypatch,
):
    store = Store(tmp_path / "worker.sqlite3")
    store.initialize()
    job_id = MarketingService(store).enqueue_sync()
    monkeypatch.setattr(worker, "store", store)

    assert worker.run_once() is True
    assert worker.run_once() is False
    with store.connect() as conn:
        job = conn.execute(
            "SELECT * FROM job_queue WHERE id=?",
            (job_id,),
        ).fetchone()
    assert job["status"] == "succeeded"
    assert job["attempts"] == 1
    assert job["finished_at"]
