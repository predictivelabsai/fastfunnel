"""Semantic KPI queries, custom fields, and governed destination exports."""

from __future__ import annotations

import json
from typing import Any

from fastfunnel.domain.store import Store, new_id, now_iso
from fastfunnel.integrations.destinations import (
    FastSMEDestination,
    GoogleSheetsDestination,
)

BASE_METRICS = {
    "impressions",
    "clicks",
    "spend",
    "conversions",
    "sessions",
    "engaged_sessions",
    "emails_sent",
    "emails_delivered",
    "email_unique_opens",
    "email_unique_clicks",
}

DEFAULT_KPIS = (
    ("ctr", "Click-through rate", "clicks", "impressions", "percent"),
    ("cpc", "Cost per click", "spend", "clicks", "currency"),
    ("conversion_rate", "Conversion rate", "conversions", "clicks", "percent"),
    ("email_open_rate", "Email open rate", "email_unique_opens", "emails_delivered", "percent"),
    ("email_click_rate", "Email click rate", "email_unique_clicks", "emails_delivered", "percent"),
)


class AnalyticsService:
    def __init__(self, store: Store):
        self.store = store

    def seed(self, company_id: str | None = None) -> None:
        company_id = company_id or self.store.default_company_id()
        timestamp = now_iso()
        with self.store.connect() as conn:
            for slug, name, numerator, denominator, display in DEFAULT_KPIS:
                conn.execute(
                    """INSERT OR IGNORE INTO kpi_definitions
                       (id, company_id, slug, name, numerator_metric,
                        denominator_metric, format, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"kpi_{company_id}_{slug}",
                        company_id,
                        slug,
                        name,
                        numerator,
                        denominator,
                        display,
                        timestamp,
                        timestamp,
                    ),
                )

    def kpis(self, company_id: str | None = None) -> list[dict[str, Any]]:
        company_id = company_id or self.store.default_company_id()
        self.seed(company_id)
        with self.store.connect() as conn:
            facts = conn.execute(
                """SELECT metric, SUM(value) value FROM marketing_facts
                   WHERE company_id=? GROUP BY metric""",
                (company_id,),
            ).fetchall()
            definitions = conn.execute(
                """SELECT * FROM kpi_definitions
                   WHERE company_id=? AND enabled=1 ORDER BY name""",
                (company_id,),
            ).fetchall()
        values = {row["metric"]: float(row["value"]) for row in facts}
        output = []
        for definition in definitions:
            numerator = values.get(definition["numerator_metric"], 0.0)
            denominator_metric = definition["denominator_metric"]
            denominator = values.get(denominator_metric, 0.0) if denominator_metric else None
            value = numerator if denominator is None else numerator / denominator if denominator else 0.0
            output.append({**dict(definition), "value": value, "components": {
                "numerator": numerator, "denominator": denominator
            }})
        return output

    def explore(
        self,
        *,
        company_id: str,
        metric: str,
        dimension: str = "fact_date",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if metric not in BASE_METRICS:
            raise ValueError("Metric is not allow-listed")
        dimensions = {
            "fact_date": "fact_date",
            "provider": "provider",
            "campaign": "campaign_external_id",
        }
        if dimension not in dimensions:
            raise ValueError("Dimension is not allow-listed")
        column = dimensions[dimension]
        limit = min(max(limit, 1), 1000)
        with self.store.connect() as conn:
            rows = conn.execute(
                f"""SELECT {column} dimension, SUM(value) value
                    FROM marketing_facts
                    WHERE company_id=? AND metric=?
                    GROUP BY {column} ORDER BY {column} DESC LIMIT ?""",
                (company_id, metric, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_query(
        self,
        *,
        company_id: str,
        actor_id: str,
        name: str,
        metric: str,
        dimension: str,
    ) -> str:
        self.explore(company_id=company_id, metric=metric, dimension=dimension, limit=1)
        query_id = new_id("qry")
        timestamp = now_iso()
        with self.store.connect() as conn:
            conn.execute(
                """INSERT INTO saved_queries
                   (id, company_id, name, definition_json, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    query_id,
                    company_id,
                    name.strip(),
                    json.dumps({"metric": metric, "dimension": dimension}),
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
        return query_id

    def export(
        self,
        *,
        company_id: str,
        saved_query_id: str,
        destination_id: str,
    ) -> dict:
        with self.store.connect() as conn:
            query = conn.execute(
                "SELECT * FROM saved_queries WHERE id=? AND company_id=?",
                (saved_query_id, company_id),
            ).fetchone()
            destination = conn.execute(
                "SELECT * FROM destination_connections WHERE id=? AND company_id=?",
                (destination_id, company_id),
            ).fetchone()
        if not query or not destination:
            raise LookupError("Unknown query or destination for tenant")
        definition = json.loads(query["definition_json"])
        rows = self.explore(company_id=company_id, **definition)
        providers = {
            "google-sheets": GoogleSheetsDestination,
            "fastsme": FastSMEDestination,
        }
        try:
            adapter = providers[destination["provider"]]()
        except KeyError as exc:
            raise LookupError("Unsupported destination provider") from exc
        run_id = new_id("exp")
        with self.store.connect() as conn:
            conn.execute(
                """INSERT INTO export_runs
                   (id, company_id, destination_id, saved_query_id, status, started_at)
                   VALUES (?, ?, ?, ?, 'running', ?)""",
                (run_id, company_id, destination_id, saved_query_id, now_iso()),
            )
        try:
            receipt = adapter.export(rows, json.loads(destination["config_json"]))
            with self.store.connect() as conn:
                conn.execute(
                    """UPDATE export_runs SET status='succeeded', rows_written=?,
                       receipt_json=?, finished_at=? WHERE id=?""",
                    (receipt.rows_written, json.dumps(receipt.details), now_iso(), run_id),
                )
            return {"run_id": run_id, "rows": receipt.rows_written, "receipt": receipt.details}
        except Exception as exc:
            with self.store.connect() as conn:
                conn.execute(
                    """UPDATE export_runs SET status='failed', error=?, finished_at=?
                       WHERE id=?""",
                    (str(exc), now_iso(), run_id),
                )
            raise
