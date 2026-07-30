"""Durable, replayable ingestion for analytics, CRM, and lifecycle sources."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastfunnel.domain.store import Store, new_id, now_iso
from fastfunnel.integrations.sources import SourceBatch, SourceConnector


class IngestionService:
    def __init__(self, store: Store):
        self.store = store

    def ensure_source(
        self,
        connector: SourceConnector,
        *,
        company_id: str | None = None,
        name: str | None = None,
    ) -> str:
        company_id = company_id or self.store.default_company_id()
        source_id = f"src_{company_id}_{connector.provider}".replace("-", "_")
        created = now_iso()
        status, _ = connector.readiness()
        with self.store.connect() as conn:
            conn.execute(
                """INSERT INTO data_sources
                   (id, company_id, provider, name, mode, status, config_json,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?)
                   ON CONFLICT(id) DO UPDATE SET mode=excluded.mode,
                     status=excluded.status, updated_at=excluded.updated_at""",
                (
                    source_id,
                    company_id,
                    connector.provider,
                    name or connector.provider.replace("-", " ").title(),
                    connector.mode,
                    status,
                    created,
                    created,
                ),
            )
            conn.execute(
                """INSERT OR IGNORE INTO sync_cursors
                   (data_source_id, cursor_json, updated_at) VALUES (?, '{}', ?)""",
                (source_id, created),
            )
        return source_id

    def sync(
        self,
        connector: SourceConnector,
        *,
        company_id: str | None = None,
        lookback_days: int = 30,
    ) -> dict:
        company_id = company_id or self.store.default_company_id()
        source_id = self.ensure_source(connector, company_id=company_id)
        end = datetime.now(UTC).date()
        start = end - timedelta(days=max(1, lookback_days) - 1)
        with self.store.connect() as conn:
            cursor_row = conn.execute(
                "SELECT cursor_json FROM sync_cursors WHERE data_source_id=?", (source_id,)
            ).fetchone()
        cursor = json.loads(cursor_row["cursor_json"]) if cursor_row else {}
        batch = connector.fetch(start, end, cursor)
        run_id = self._start_run(company_id, source_id, connector.provider)
        try:
            rows = self._persist_batch(company_id, source_id, run_id, batch)
            with self.store.connect() as conn:
                conn.execute(
                    """UPDATE sync_cursors SET cursor_json=?, watermark_at=?, updated_at=?
                       WHERE data_source_id=?""",
                    (json.dumps(batch.next_cursor), end.isoformat(), now_iso(), source_id),
                )
                conn.execute(
                    """UPDATE sync_runs SET status='succeeded', finished_at=?,
                       rows_written=?, cursor_json=? WHERE id=?""",
                    (now_iso(), rows, json.dumps(batch.next_cursor), run_id),
                )
                conn.execute(
                    "UPDATE data_sources SET status='available', updated_at=? WHERE id=?",
                    (now_iso(), source_id),
                )
            return {"run_id": run_id, "source_id": source_id, "status": "succeeded", "rows": rows}
        except Exception as exc:
            with self.store.connect() as conn:
                conn.execute(
                    """UPDATE sync_runs SET status='failed', finished_at=?, error=?
                       WHERE id=?""",
                    (now_iso(), str(exc), run_id),
                )
                conn.execute(
                    "UPDATE data_sources SET status='degraded', updated_at=? WHERE id=?",
                    (now_iso(), source_id),
                )
            raise

    def _start_run(self, company_id: str, source_id: str, provider: str) -> str:
        run_id = new_id("sync")
        connection_id = self._ensure_connection(company_id, provider)
        with self.store.connect() as conn:
            conn.execute(
                """INSERT INTO sync_runs
                   (id, company_id, connection_id, provider, started_at, status)
                   VALUES (?, ?, ?, ?, ?, 'running')""",
                (run_id, company_id, connection_id, provider, now_iso()),
            )
        return run_id

    def _ensure_connection(self, company_id: str, provider: str) -> str:
        connection_id = f"conn_{company_id}_{provider}".replace("-", "_")
        with self.store.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO integration_connections
                   (id, company_id, provider, mode, status, capabilities_json, created_at)
                   VALUES (?, ?, ?, 'synthetic', 'available', '["data.read"]', ?)""",
                (connection_id, company_id, provider, now_iso()),
            )
            row = conn.execute(
                """SELECT id FROM integration_connections
                   WHERE company_id=? AND provider=?""",
                (company_id, provider),
            ).fetchone()
        return row["id"]

    def _persist_batch(
        self,
        company_id: str,
        source_id: str,
        run_id: str,
        batch: SourceBatch,
    ) -> int:
        ingested = now_iso()
        with self.store.connect() as conn:
            account_id = f"acct_{company_id}_{batch.provider}_{batch.account_external_id}"
            conn.execute(
                """INSERT INTO platform_accounts
                   (id, company_id, provider, external_id, display_name, status,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'available', ?, ?)
                   ON CONFLICT(company_id, provider, external_id) DO UPDATE SET
                     display_name=excluded.display_name, updated_at=excluded.updated_at""",
                (
                    account_id,
                    company_id,
                    batch.provider,
                    batch.account_external_id,
                    batch.account_name,
                    ingested,
                    ingested,
                ),
            )
            conn.execute(
                "UPDATE data_sources SET platform_account_id=? WHERE id=?",
                (account_id, source_id),
            )
            for record in batch.records:
                canonical = json.dumps(record.payload, sort_keys=True, separators=(",", ":"))
                digest = hashlib.sha256(canonical.encode()).hexdigest()
                conn.execute(
                    """INSERT OR IGNORE INTO raw_extracts
                       (id, company_id, data_source_id, sync_run_id, provider,
                        object_type, partition_key, payload_json, payload_hash,
                        source_updated_at, ingested_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        new_id("raw"),
                        company_id,
                        source_id,
                        run_id,
                        batch.provider,
                        record.object_type,
                        record.partition_key,
                        canonical,
                        digest,
                        record.source_updated_at,
                        ingested,
                    ),
                )
                self._normalize(conn, company_id, batch.provider, record, ingested)
        return len(batch.records)

    @staticmethod
    def _normalize(conn, company_id: str, provider: str, record, ingested: str) -> None:
        if record.object_type == "contact":
            payload = record.payload
            attributes = payload.get("attributes", {})
            stage = (
                payload.get("lifecyclestage")
                or attributes.get("STAGE")
                or payload.get("hs_lead_status")
                or "subscriber"
            )
            conn.execute(
                """INSERT INTO crm_entities
                   (id, company_id, provider, external_id, entity_type,
                    lifecycle_stage, occurred_at, revenue_value, currency,
                    properties_json, source_updated_at, ingested_at)
                   VALUES (?, ?, ?, ?, 'contact', ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(company_id, provider, entity_type, external_id) DO UPDATE SET
                     lifecycle_stage=excluded.lifecycle_stage,
                     revenue_value=excluded.revenue_value,
                     properties_json=excluded.properties_json,
                     source_updated_at=excluded.source_updated_at,
                     ingested_at=excluded.ingested_at""",
                (
                    (
                        f"crm_{hashlib.sha256(company_id.encode()).hexdigest()[:12]}_"
                        f"{provider}_{record.external_id}"
                    ),
                    company_id,
                    provider,
                    record.external_id,
                    stage,
                    record.source_updated_at,
                    float(payload.get("amount") or 0),
                    payload.get("currency") or "",
                    json.dumps(payload, sort_keys=True),
                    record.source_updated_at,
                    ingested,
                ),
            )
        elif record.object_type in {"email_campaign", "analytics_report"}:
            payload = record.payload
            metric_map = {
                "sent": "emails_sent",
                "delivered": "emails_delivered",
                "uniqueOpens": "email_unique_opens",
                "uniqueClicks": "email_unique_clicks",
                "sessions": "sessions",
                "engagedSessions": "engaged_sessions",
                "conversions": "conversions",
            }
            for source_name, metric in metric_map.items():
                value = payload.get(source_name)
                if value is None:
                    continue
                conn.execute(
                    """INSERT INTO marketing_facts
                       (company_id, provider, account_id, campaign_external_id,
                        fact_date, metric, value, source_updated_at, ingested_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(
                         company_id, provider, account_id, campaign_external_id,
                         fact_date, metric, dimensions_json
                       ) DO UPDATE SET value=excluded.value,
                         source_updated_at=excluded.source_updated_at,
                         ingested_at=excluded.ingested_at""",
                    (
                        company_id,
                        provider,
                        f"{provider}-account",
                        record.external_id,
                        record.partition_key[:10],
                        metric,
                        float(value),
                        record.source_updated_at,
                        ingested,
                    ),
                )

    def replay(self, source_id: str, *, company_id: str) -> int:
        """Rebuild normalized rows from immutable extracts for one tenant/source."""
        with self.store.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM raw_extracts
                   WHERE company_id=? AND data_source_id=? ORDER BY ingested_at""",
                (company_id, source_id),
            ).fetchall()
            for row in rows:
                record = type(
                    "ReplayRecord",
                    (),
                    {
                        "object_type": row["object_type"],
                        "external_id": row["id"],
                        "partition_key": row["partition_key"],
                        "source_updated_at": row["source_updated_at"] or row["ingested_at"],
                        "payload": json.loads(row["payload_json"]),
                    },
                )
                self._normalize(conn, company_id, row["provider"], record, now_iso())
        return len(rows)
