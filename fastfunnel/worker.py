"""Separate durable worker process for FastFunnel background jobs."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta

from fastfunnel.domain.actions import ActionService
from fastfunnel.domain.ingestion import IngestionService
from fastfunnel.domain.marketing import MarketingService
from fastfunnel.domain.store import store
from fastfunnel.integrations.sources import BrevoConnector, GA4SourceConnector, HubSpotConnector


def run_once() -> bool:
    with store.connect() as conn:
        job = conn.execute(
            """SELECT * FROM job_queue
               WHERE status='pending' AND available_at<=?
               ORDER BY created_at LIMIT 1""",
            (datetime.now(UTC).isoformat(),),
        ).fetchone()
        if not job:
            return False
        conn.execute(
            """UPDATE job_queue SET status='running', locked_at=datetime('now'),
               attempts=attempts+1 WHERE id=? AND status='pending'""",
            (job["id"],),
        )
    try:
        if job["job_type"] == "sync.google_ads":
            MarketingService(store).sync_google_ads(job["company_id"])
        elif job["job_type"].startswith("sync."):
            provider = job["job_type"].split(".", 1)[1]
            connectors = {
                "hubspot": HubSpotConnector,
                "brevo": BrevoConnector,
                "ga4": GA4SourceConnector,
            }
            try:
                connector_type = connectors[provider]
            except KeyError as exc:
                raise ValueError(f"Unsupported sync provider: {provider}") from exc
            payload = json.loads(job["payload_json"])
            IngestionService(store).sync(
                connector_type(payload.get("mode", "synthetic")),
                company_id=job["company_id"],
                lookback_days=int(payload.get("lookback_days", 30)),
            )
        elif job["job_type"] == "action.execute":
            payload = json.loads(job["payload_json"])
            ActionService(store).execute(payload["action_request_id"])
        else:
            raise ValueError(f"Unsupported job type: {job['job_type']}")
        with store.connect() as conn:
            conn.execute(
                """UPDATE job_queue SET status='succeeded', finished_at=datetime('now')
                   WHERE id=?""",
                (job["id"],),
            )
        return True
    except (RuntimeError, ValueError, PermissionError, LookupError) as exc:
        with store.connect() as conn:
            attempts = int(job["attempts"]) + 1
            delay_seconds = min(3600, 15 * (2 ** max(0, attempts - 1)))
            available_at = (datetime.now(UTC) + timedelta(seconds=delay_seconds)).isoformat()
            conn.execute(
                """UPDATE job_queue SET status=CASE WHEN attempts>=max_attempts
                       THEN 'failed' ELSE 'pending' END, last_error=?, available_at=?
                       WHERE id=?""",
                (str(exc), available_at, job["id"]),
            )
        return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    store.initialize()
    while True:
        worked = run_once()
        if args.once:
            return
        if not worked:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
