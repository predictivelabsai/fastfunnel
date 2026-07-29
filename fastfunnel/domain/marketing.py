"""Marketing ingestion, funnel read models, and durable job operations."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta

from fastfunnel.domain.funnels import FunnelStage, sankey_spec
from fastfunnel.domain.store import Store, new_id, now_iso
from fastfunnel.integrations.marketing import GoogleAdsConnector, MarketingReadConnector

DEFAULT_FUNNEL_ID = "fnl_digital_marketing"
DEFAULT_STAGES = (
    ("Impressions", "Impressions", "No click", {"minimum_stage": 0}),
    ("Clicks", "Clicks", "No engaged visit", {"minimum_stage": 1}),
    ("Engaged visits", "Engaged", "Did not engage", {"minimum_stage": 2}),
    ("Leads", "Leads", "No lead", {"minimum_stage": 3}),
    ("Qualified leads", "Qualified", "Not qualified", {"minimum_stage": 4}),
    ("Customers", "Customers", "Not converted", {"minimum_stage": 5}),
)


class MarketingService:
    def __init__(self, store: Store):
        self.store = store

    def seed(self) -> None:
        with self.store.connect() as conn:
            company = conn.execute("SELECT * FROM companies LIMIT 1").fetchone()
            if not company:
                return
            created = now_iso()
            conn.execute(
                """INSERT OR IGNORE INTO integration_connections
                   (id, company_id, provider, mode, status, capabilities_json, created_at)
                   VALUES (?, ?, 'google-ads', 'synthetic', 'available', ?, ?)""",
                (
                    "conn_google_ads_synthetic",
                    company["id"],
                    json.dumps(["campaigns.read", "performance.read"]),
                    created,
                ),
            )
            for provider, capabilities in (
                ("hubspot", ["contacts.read", "lifecycle.read", "revenue.read"]),
                ("brevo", ["campaigns.read", "contacts.read", "performance.read"]),
                ("composio", ["tools.execute", "auth.delegate"]),
                ("arcade", ["tools.execute", "auth.delegate"]),
                ("google-sheets", ["data.export"]),
                ("fastsme", ["data.export"]),
            ):
                conn.execute(
                    """INSERT OR IGNORE INTO integration_connections
                       (id, company_id, provider, mode, status, capabilities_json, created_at)
                       VALUES (?, ?, ?, 'credentials-required', 'available', ?, ?)""",
                    (
                        f"conn_{provider.replace('-', '_')}_pending",
                        company["id"],
                        provider,
                        json.dumps(capabilities),
                        created,
                    ),
                )
            conn.execute(
                """INSERT OR IGNORE INTO integration_connections
                   (id, company_id, provider, mode, status, capabilities_json, created_at)
                   VALUES (?, ?, 'ga4', 'credentials-required', 'stub', ?, ?)""",
                (
                    "conn_ga4_pending",
                    company["id"],
                    json.dumps(["analytics.read"]),
                    created,
                ),
            )
            conn.execute(
                """INSERT OR IGNORE INTO funnel_definitions
                   (id, company_id, name, slug, description, is_default,
                    observation_window_days, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, 30, ?, ?)""",
                (
                    DEFAULT_FUNNEL_ID,
                    company["id"],
                    "Digital marketing acquisition",
                    "digital-marketing-acquisition",
                    "Paid and organic demand from impression to customer.",
                    created,
                    created,
                ),
            )
            for position, (name, short, dropoff, predicate) in enumerate(DEFAULT_STAGES):
                conn.execute(
                    """INSERT OR IGNORE INTO funnel_stages
                       (id, funnel_id, position, name, short_name, dropoff_name, predicate_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"fst_digital_{position}",
                        DEFAULT_FUNNEL_ID,
                        position,
                        name,
                        short,
                        dropoff,
                        json.dumps(predicate),
                    ),
                )
            existing = conn.execute(
                "SELECT COUNT(*) FROM journey_entities WHERE company_id=?", (company["id"],)
            ).fetchone()[0]
            if not existing:
                self._seed_journeys(conn, company["id"])

        self.sync_google_ads()
        from fastfunnel.domain.analytics import AnalyticsService
        from fastfunnel.domain.ingestion import IngestionService
        from fastfunnel.integrations.sources import (
            BrevoConnector,
            GA4SourceConnector,
            HubSpotConnector,
        )

        ingestion = IngestionService(self.store)
        company_id = self.store.default_company_id()
        for connector in (
            HubSpotConnector("synthetic"),
            BrevoConnector("synthetic"),
            GA4SourceConnector("synthetic"),
        ):
            ingestion.sync(connector, company_id=company_id)
        AnalyticsService(self.store).seed(company_id)

    @staticmethod
    def _seed_journeys(conn, company_id: str) -> None:
        rng = random.Random(42)
        today = datetime.now(UTC).date()
        thresholds = (1.0, 0.42, 0.28, 0.115, 0.058, 0.021)
        rows = []
        for index in range(1200):
            draw = rng.random()
            reached = 0
            for stage, threshold in enumerate(thresholds):
                if draw <= threshold:
                    reached = stage
            campaign = "gads_search_ai" if index % 3 else "gads_retargeting"
            rows.append(
                (
                    f"jny_{index:05}",
                    company_id,
                    (today - timedelta(days=index % 30)).isoformat(),
                    "google-ads",
                    campaign,
                    reached,
                    json.dumps({"synthetic": True, "cohort": "launch"}),
                )
            )
        conn.executemany(
            """INSERT INTO journey_entities
               (id, company_id, occurred_on, source, campaign_external_id,
                reached_stage, attributes_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    def sync_google_ads(self, company_id: str | None = None) -> dict:
        return self.sync_connector(
            GoogleAdsConnector(mode="synthetic"),
            lookback_days=30,
            company_id=company_id,
        )

    def sync_connector(
        self,
        connector: MarketingReadConnector,
        lookback_days: int = 30,
        company_id: str | None = None,
    ) -> dict:
        company_id = company_id or self.store.default_company_id()
        run_id = new_id("sync")
        started = now_iso()
        end = datetime.now(UTC).date()
        start = end - timedelta(days=lookback_days - 1)
        with self.store.connect() as conn:
            company = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
            connection = conn.execute(
                """SELECT * FROM integration_connections
                   WHERE company_id=? AND provider=?""",
                (company["id"], connector.provider),
            ).fetchone()
            conn.execute(
                """INSERT INTO sync_runs
                   (id, company_id, connection_id, provider, started_at, status)
                   VALUES (?, ?, ?, ?, ?, 'running')""",
                (run_id, company["id"], connection["id"], connector.provider, started),
            )
        try:
            campaigns, facts = connector.fetch(start, end)
            ingested = now_iso()
            with self.store.connect() as conn:
                company = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
                for campaign in campaigns:
                    conn.execute(
                        """INSERT INTO campaigns
                           (id, company_id, provider, external_id, name, channel, status,
                            daily_budget, currency, first_seen_at, last_seen_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(company_id, provider, external_id) DO UPDATE SET
                           name=excluded.name, channel=excluded.channel, status=excluded.status,
                           daily_budget=excluded.daily_budget, currency=excluded.currency,
                           last_seen_at=excluded.last_seen_at""",
                        (
                            f"cmp_{campaign.external_id}",
                            company["id"],
                            connector.provider,
                            campaign.external_id,
                            campaign.name,
                            campaign.channel,
                            campaign.status,
                            campaign.daily_budget,
                            campaign.currency,
                            ingested,
                            ingested,
                        ),
                    )
                for fact in facts:
                    conn.execute(
                        """INSERT INTO marketing_facts
                           (company_id, provider, account_id, campaign_external_id,
                            fact_date, metric, value, currency, source_updated_at, ingested_at)
                           VALUES (?, ?, 'synthetic-account', ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(
                             company_id, provider, account_id, campaign_external_id,
                             fact_date, metric, dimensions_json
                           ) DO UPDATE SET value=excluded.value, currency=excluded.currency,
                             source_updated_at=excluded.source_updated_at,
                             ingested_at=excluded.ingested_at""",
                        (
                            company["id"],
                            connector.provider,
                            fact.campaign_external_id,
                            fact.fact_date,
                            fact.metric,
                            fact.value,
                            fact.currency,
                            ingested,
                            ingested,
                        ),
                    )
                conn.execute(
                    """UPDATE sync_runs SET status='succeeded', finished_at=?,
                       rows_written=?, cursor_json=? WHERE id=?""",
                    (
                        now_iso(),
                        len(facts),
                        json.dumps({"start": start.isoformat(), "end": end.isoformat()}),
                        run_id,
                    ),
                )
                conn.execute(
                    """UPDATE integration_connections
                       SET status='available', last_checked_at=?
                       WHERE company_id=? AND provider=?""",
                    (now_iso(), company_id, connector.provider),
                )
            return {"run_id": run_id, "status": "succeeded", "rows": len(facts)}
        except Exception as exc:
            with self.store.connect() as conn:
                conn.execute(
                    """UPDATE sync_runs SET status='failed', finished_at=?, error=?
                       WHERE id=?""",
                    (now_iso(), str(exc), run_id),
                )
            raise

    def analytics_summary(self, company_id: str | None = None) -> dict:
        company_id = company_id or self.store.default_company_id()
        with self.store.connect() as conn:
            company = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
            rows = conn.execute(
                """SELECT metric, SUM(value) AS value
                   FROM marketing_facts WHERE company_id=? GROUP BY metric""",
                (company["id"],),
            ).fetchall()
            metrics = {row["metric"]: float(row["value"]) for row in rows}
            latest = conn.execute(
                """SELECT provider, status, rows_written, finished_at
                   FROM sync_runs WHERE company_id=?
                   ORDER BY started_at DESC LIMIT 1""",
                (company["id"],),
            ).fetchone()
            return {"metrics": metrics, "latest_sync": dict(latest) if latest else None}

    def funnel(
        self,
        funnel_id: str = DEFAULT_FUNNEL_ID,
        days: int = 30,
        company_id: str | None = None,
    ) -> dict:
        company_id = company_id or self.store.default_company_id()
        with self.store.connect() as conn:
            funnel = conn.execute(
                "SELECT * FROM funnel_definitions WHERE id=? AND company_id=?",
                (funnel_id, company_id),
            ).fetchone()
            if not funnel:
                raise LookupError(f"Unknown funnel: {funnel_id}")
            stage_rows = conn.execute(
                "SELECT * FROM funnel_stages WHERE funnel_id=? ORDER BY position",
                (funnel_id,),
            ).fetchall()
            since = (datetime.now(UTC).date() - timedelta(days=days - 1)).isoformat()
            stages = []
            for row in stage_rows:
                predicate = json.loads(row["predicate_json"])
                count = conn.execute(
                    """SELECT COUNT(*) FROM journey_entities
                       WHERE company_id=? AND occurred_on>=? AND reached_stage>=?""",
                    (funnel["company_id"], since, int(predicate["minimum_stage"])),
                ).fetchone()[0]
                stages.append(
                    FunnelStage(
                        row["name"], row["short_name"], row["dropoff_name"], count
                    )
                )
            result = sankey_spec(stages)
            result.update(
                {
                    "definition": dict(funnel),
                    "stages": stages,
                    "days": days,
                    "since": since,
                }
            )
            return result

    def enqueue_sync(self, company_id: str | None = None) -> str:
        company_id = company_id or self.store.default_company_id()
        today = datetime.now(UTC).date().isoformat()
        job_id = new_id("job")
        with self.store.connect() as conn:
            company = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
            conn.execute(
                """INSERT OR IGNORE INTO job_queue
                   (id, company_id, job_type, payload_json, idempotency_key,
                    status, available_at, created_at)
                   VALUES (?, ?, 'sync.google_ads', '{}', ?, 'pending', ?, ?)""",
                (job_id, company["id"], f"google-ads:{today}", now_iso(), now_iso()),
            )
            row = conn.execute(
                "SELECT id FROM job_queue WHERE company_id=? AND idempotency_key=?",
                (company["id"], f"google-ads:{today}"),
            ).fetchone()
            return row["id"]
