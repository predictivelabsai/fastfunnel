"""Separate durable worker process for FastFunnel background jobs."""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime

from fastfunnel.domain.marketing import MarketingService
from fastfunnel.domain.store import store


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
            MarketingService(store).sync_google_ads()
        else:
            raise ValueError(f"Unsupported job type: {job['job_type']}")
        with store.connect() as conn:
            conn.execute(
                """UPDATE job_queue SET status='succeeded', finished_at=datetime('now')
                   WHERE id=?""",
                (job["id"],),
            )
        return True
    except (RuntimeError, ValueError) as exc:
        with store.connect() as conn:
            conn.execute(
                """UPDATE job_queue SET status=CASE WHEN attempts>=max_attempts
                       THEN 'failed' ELSE 'pending' END, last_error=? WHERE id=?""",
                (str(exc), job["id"]),
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
