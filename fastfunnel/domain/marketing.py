"""Marketing ingestion, funnel read models, and durable job operations."""

from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import UTC, datetime, timedelta

from fastfunnel.domain.funnels import FunnelStage, sankey_spec
from fastfunnel.domain.store import Store, new_id, now_iso
from fastfunnel.domain.workspace import WorkspaceConfiguration
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
            company_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM companies ORDER BY created_at"
                ).fetchall()
            ]
        for company_id in company_ids:
            self.seed_company(company_id)

    @staticmethod
    def _tenant_token(company_id: str) -> str:
        return hashlib.sha256(company_id.encode()).hexdigest()[:12]

    @classmethod
    def default_funnel_id(cls, company_id: str) -> str:
        if company_id == "co_predictivelabs":
            return DEFAULT_FUNNEL_ID
        return f"{DEFAULT_FUNNEL_ID}_{cls._tenant_token(company_id)}"

    @classmethod
    def _scoped_id(cls, prefix: str, company_id: str) -> str:
        if company_id == "co_predictivelabs":
            return prefix
        return f"{prefix}_{cls._tenant_token(company_id)}"

    def seed_company(self, company_id: str) -> None:
        funnel_id = self.default_funnel_id(company_id)
        with self.store.connect() as conn:
            company = conn.execute(
                "SELECT * FROM companies WHERE id=?", (company_id,)
            ).fetchone()
            if not company:
                raise LookupError("Unknown company")
            created = now_iso()
            conn.execute(
                """INSERT OR IGNORE INTO integration_connections
                   (id, company_id, provider, mode, status, capabilities_json, created_at)
                   VALUES (?, ?, 'google-ads', 'synthetic', 'available', ?, ?)""",
                (
                    self._scoped_id("conn_google_ads_synthetic", company_id),
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
                        self._scoped_id(
                            f"conn_{provider.replace('-', '_')}_pending",
                            company_id,
                        ),
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
                    self._scoped_id("conn_ga4_pending", company_id),
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
                    funnel_id,
                    company["id"],
                    "Digital marketing acquisition",
                    "digital-marketing-acquisition",
                    "Paid and organic demand from impression to customer.",
                    created,
                    created,
                ),
            )
            funnel_id = conn.execute(
                """SELECT id FROM funnel_definitions
                   WHERE company_id=? AND slug='digital-marketing-acquisition'""",
                (company_id,),
            ).fetchone()["id"]
            for position, (name, short, dropoff, predicate) in enumerate(DEFAULT_STAGES):
                conn.execute(
                    """INSERT OR IGNORE INTO funnel_stages
                       (id, funnel_id, position, name, short_name, dropoff_name, predicate_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        self._scoped_id(f"fst_digital_{position}", company_id),
                        funnel_id,
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

        with self.store.connect() as conn:
            has_google_ads = conn.execute(
                """SELECT 1 FROM marketing_facts
                   WHERE company_id=? AND provider='google-ads' LIMIT 1""",
                (company_id,),
            ).fetchone()
        if not has_google_ads:
            self.sync_google_ads(company_id)
        from fastfunnel.domain.analytics import AnalyticsService
        from fastfunnel.domain.ingestion import IngestionService
        from fastfunnel.integrations.sources import (
            BrevoConnector,
            GA4SourceConnector,
            HubSpotConnector,
        )

        ingestion = IngestionService(self.store)
        for connector in (
            HubSpotConnector("synthetic"),
            BrevoConnector("synthetic"),
            GA4SourceConnector("synthetic"),
        ):
            with self.store.connect() as conn:
                has_source = conn.execute(
                    """SELECT 1 FROM data_sources
                       WHERE company_id=? AND provider=? LIMIT 1""",
                    (company_id, connector.provider),
                ).fetchone()
            if not has_source:
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
                    f"jny_{MarketingService._tenant_token(company_id)}_{index:05}",
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
                            (
                                f"cmp_{self._tenant_token(company_id)}_"
                                f"{campaign.external_id}"
                            ),
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

    def campaign_summary(self, company_id: str | None = None) -> dict:
        company_id = company_id or self.store.default_company_id()
        with self.store.connect() as conn:
            campaigns = conn.execute(
                """SELECT campaigns.*,
                          COALESCE(SUM(CASE WHEN marketing_facts.metric='spend'
                                    THEN marketing_facts.value ELSE 0 END), 0) AS spend,
                          COALESCE(SUM(CASE WHEN marketing_facts.metric='clicks'
                                    THEN marketing_facts.value ELSE 0 END), 0) AS clicks,
                          COALESCE(SUM(CASE WHEN marketing_facts.metric='conversions'
                                    THEN marketing_facts.value ELSE 0 END), 0) AS conversions
                   FROM campaigns
                   LEFT JOIN marketing_facts
                     ON marketing_facts.company_id=campaigns.company_id
                    AND marketing_facts.provider=campaigns.provider
                    AND marketing_facts.campaign_external_id=campaigns.external_id
                   WHERE campaigns.company_id=?
                   GROUP BY campaigns.id
                   ORDER BY spend DESC, campaigns.name""",
                (company_id,),
            ).fetchall()
            latest_sync = conn.execute(
                """SELECT id, provider, status, rows_written, started_at, finished_at
                   FROM sync_runs
                   WHERE company_id=? AND provider='google-ads'
                   ORDER BY started_at DESC LIMIT 1""",
                (company_id,),
            ).fetchone()
            pending_job = conn.execute(
                """SELECT id, status, created_at FROM job_queue
                   WHERE company_id=? AND job_type='sync.google_ads'
                     AND status IN ('pending', 'running')
                   ORDER BY created_at DESC LIMIT 1""",
                (company_id,),
            ).fetchone()
        return {
            "campaigns": [dict(row) for row in campaigns],
            "latest_sync": dict(latest_sync) if latest_sync else None,
            "pending_job": dict(pending_job) if pending_job else None,
        }

    def funnel(
        self,
        funnel_id: str | None = None,
        days: int = 30,
        company_id: str | None = None,
    ) -> dict:
        company_id = company_id or self.store.default_company_id()
        with self.store.connect() as conn:
            if funnel_id:
                funnel = conn.execute(
                    "SELECT * FROM funnel_definitions WHERE id=? AND company_id=?",
                    (funnel_id, company_id),
                ).fetchone()
            else:
                funnel = conn.execute(
                    """SELECT * FROM funnel_definitions
                       WHERE company_id=?
                       ORDER BY is_default DESC, created_at LIMIT 1""",
                    (company_id,),
                ).fetchone()
            if not funnel:
                raise LookupError(
                    f"Unknown funnel: {funnel_id or 'default for workspace'}"
                )
            funnel_id = funnel["id"]
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

    def list_funnels(self, company_id: str) -> list[dict]:
        with self.store.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM funnel_definitions
                   WHERE company_id=?
                   ORDER BY is_default DESC, name""",
                (company_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_funnel(
        self,
        *,
        company_id: str,
        actor_id: str,
        name: str,
        description: str,
        observation_window_days: int,
        stages: list[tuple[str, str, str]],
        funnel_id: str | None = None,
        is_default: bool = False,
    ) -> str:
        name = name.strip()
        description = description.strip()
        observation_window_days = int(observation_window_days)
        if not 3 <= len(name) <= 100:
            raise ValueError("Funnel name must contain 3 to 100 characters")
        if not 1 <= observation_window_days <= 365:
            raise ValueError("Observation window must be between 1 and 365 days")
        if not 2 <= len(stages) <= 12:
            raise ValueError("A funnel must contain between 2 and 12 stages")
        cleaned_stages = []
        for stage_name, short_name, dropoff_name in stages:
            stage = stage_name.strip()
            short = short_name.strip() or stage
            dropoff = dropoff_name.strip() or f"Did not reach {stage}"
            if not stage or max(len(stage), len(short), len(dropoff)) > 100:
                raise ValueError("Stage labels must contain 1 to 100 characters")
            cleaned_stages.append((stage, short, dropoff))

        timestamp = now_iso()
        slug_base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        with self.store.connect() as conn:
            company = conn.execute(
                "SELECT * FROM companies WHERE id=?", (company_id,)
            ).fetchone()
            if not company:
                raise LookupError("Unknown company")
            WorkspaceConfiguration._require_admin(
                conn, company["organization_id"], actor_id
            )
            if funnel_id:
                existing = conn.execute(
                    """SELECT * FROM funnel_definitions
                       WHERE id=? AND company_id=?""",
                    (funnel_id, company_id),
                ).fetchone()
                if not existing:
                    raise LookupError("Unknown funnel")
                slug = existing["slug"]
                conn.execute(
                    """UPDATE funnel_definitions
                       SET name=?, description=?, observation_window_days=?,
                           is_default=?, updated_at=?
                       WHERE id=? AND company_id=?""",
                    (
                        name,
                        description,
                        observation_window_days,
                        int(is_default),
                        timestamp,
                        funnel_id,
                        company_id,
                    ),
                )
                conn.execute(
                    "DELETE FROM funnel_stages WHERE funnel_id=?",
                    (funnel_id,),
                )
            else:
                funnel_id = new_id("fnl")
                slug = f"{slug_base or 'funnel'}-{funnel_id[-6:]}"
                conn.execute(
                    """INSERT INTO funnel_definitions
                       (id, company_id, name, slug, description, is_default,
                        observation_window_days, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        funnel_id,
                        company_id,
                        name,
                        slug,
                        description,
                        int(is_default),
                        observation_window_days,
                        timestamp,
                        timestamp,
                    ),
                )
            if is_default:
                conn.execute(
                    """UPDATE funnel_definitions SET is_default=0
                       WHERE company_id=? AND id<>?""",
                    (company_id, funnel_id),
                )
            for position, (stage, short, dropoff) in enumerate(cleaned_stages):
                conn.execute(
                    """INSERT INTO funnel_stages
                       (id, funnel_id, position, name, short_name, dropoff_name,
                        predicate_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        new_id("fst"),
                        funnel_id,
                        position,
                        stage,
                        short,
                        dropoff,
                        json.dumps({"minimum_stage": position}),
                    ),
                )
            Store._audit(
                conn,
                company["organization_id"],
                company_id,
                actor_id,
                "funnel.saved",
                "funnel",
                funnel_id,
                {
                    "slug": slug,
                    "stage_count": len(cleaned_stages),
                    "is_default": is_default,
                },
            )
        return funnel_id

    def enqueue_sync(
        self,
        company_id: str | None = None,
        *,
        actor_id: str | None = None,
        manual: bool = False,
    ) -> str:
        company_id = company_id or self.store.default_company_id()
        today = datetime.now(UTC).date().isoformat()
        job_id = new_id("job")
        idempotency_key = (
            f"google-ads:manual:{job_id}" if manual else f"google-ads:{today}"
        )
        with self.store.connect() as conn:
            company = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
            if not company:
                raise LookupError("Unknown company")
            if actor_id:
                membership = conn.execute(
                    """SELECT 1 FROM memberships
                       WHERE organization_id=? AND user_id=?""",
                    (company["organization_id"], actor_id),
                ).fetchone()
                if not membership:
                    raise PermissionError("Workspace membership required")
            conn.execute(
                """INSERT OR IGNORE INTO job_queue
                   (id, company_id, job_type, payload_json, idempotency_key,
                    status, available_at, created_at)
                   VALUES (?, ?, 'sync.google_ads', '{}', ?, 'pending', ?, ?)""",
                (job_id, company["id"], idempotency_key, now_iso(), now_iso()),
            )
            row = conn.execute(
                "SELECT id FROM job_queue WHERE company_id=? AND idempotency_key=?",
                (company["id"], idempotency_key),
            ).fetchone()
            if actor_id:
                Store._audit(
                    conn,
                    company["organization_id"],
                    company_id,
                    actor_id,
                    "marketing.sync.queued",
                    "job",
                    row["id"],
                    {"provider": "google-ads", "manual": manual},
                )
            return row["id"]
