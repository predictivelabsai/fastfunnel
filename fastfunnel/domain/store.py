from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastfunnel.config import settings

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
    id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL, domain TEXT NOT NULL, reporting_currency TEXT NOT NULL DEFAULT 'GBP',
    timezone TEXT NOT NULL DEFAULT 'Europe/London', profile_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    user_id TEXT NOT NULL REFERENCES users(id), role TEXT NOT NULL,
    PRIMARY KEY (organization_id, user_id)
);
CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
    email TEXT NOT NULL, role TEXT NOT NULL, token_hash TEXT NOT NULL,
    status TEXT NOT NULL, invited_by TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS content_items (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id),
    title TEXT NOT NULL, body TEXT NOT NULL, channel TEXT NOT NULL,
    status TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES users(id),
    approved_by TEXT REFERENCES users(id), scheduled_for TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id),
    action_type TEXT NOT NULL, object_type TEXT NOT NULL, object_id TEXT NOT NULL,
    payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, status TEXT NOT NULL,
    requested_by TEXT NOT NULL REFERENCES users(id), decided_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL, decided_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id TEXT NOT NULL,
    company_id TEXT, actor_id TEXT, event_type TEXT NOT NULL,
    object_type TEXT, object_id TEXT, details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or settings.database_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            if conn.execute("SELECT 1 FROM organizations LIMIT 1").fetchone():
                return
            created = now_iso()
            org_id, company_id, user_id = "org_factorio", "co_factorio", "usr_admin"
            conn.execute(
                "INSERT INTO organizations VALUES (?, ?, ?, ?)",
                (org_id, "Factorio Finance", "factorio", created),
            )
            profile = {
                "website": f"https://{settings.seed_domain}",
                "industry": "Invoice financing",
                "market": "United Kingdom",
                "approval_policy": "bounded_autonomy_admin_approval",
            }
            conn.execute(
                """INSERT INTO companies
                   (id, organization_id, name, domain, profile_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    company_id,
                    org_id,
                    settings.seed_company,
                    settings.seed_domain,
                    json.dumps(profile),
                    created,
                ),
            )
            conn.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?)",
                (user_id, settings.admin_email, "Factorio Admin", created),
            )
            conn.execute(
                "INSERT INTO memberships VALUES (?, ?, ?)", (org_id, user_id, "admin")
            )
            self._audit(
                conn, org_id, company_id, user_id, "workspace.seeded", "company", company_id, profile
            )

    def dashboard(self) -> dict:
        with self.connect() as conn:
            company = dict(conn.execute("SELECT * FROM companies LIMIT 1").fetchone())
            counts = {}
            for status in ("draft", "review", "approved", "scheduled", "published"):
                counts[status] = conn.execute(
                    "SELECT COUNT(*) FROM content_items WHERE company_id=? AND status=?",
                    (company["id"], status),
                ).fetchone()[0]
            members = conn.execute(
                """SELECT users.email, users.display_name, memberships.role
                   FROM memberships JOIN users ON users.id=memberships.user_id
                   WHERE memberships.organization_id=?""",
                (company["organization_id"],),
            ).fetchall()
            invitations = conn.execute(
                "SELECT * FROM invitations WHERE organization_id=? ORDER BY created_at DESC",
                (company["organization_id"],),
            ).fetchall()
            return {
                "company": company,
                "counts": counts,
                "members": [dict(row) for row in members],
                "invitations": [dict(row) for row in invitations],
            }

    def list_content(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM content_items ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def create_content(self, title: str, body: str, channel: str) -> str:
        item_id = new_id("cnt")
        created = now_iso()
        with self.connect() as conn:
            company = conn.execute("SELECT * FROM companies LIMIT 1").fetchone()
            conn.execute(
                """INSERT INTO content_items
                   (id, company_id, title, body, channel, status, created_by,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'review', 'usr_admin', ?, ?)""",
                (item_id, company["id"], title, body, channel, created, created),
            )
            self._audit(
                conn,
                company["organization_id"],
                company["id"],
                "usr_admin",
                "content.created",
                "content",
                item_id,
                {"channel": channel, "status": "review"},
            )
        return item_id

    def approve_content(self, item_id: str) -> None:
        with self.connect() as conn:
            item = conn.execute(
                """SELECT content_items.*, companies.organization_id
                   FROM content_items JOIN companies ON companies.id=content_items.company_id
                   WHERE content_items.id=?""",
                (item_id,),
            ).fetchone()
            if not item or item["status"] != "review":
                return
            conn.execute(
                """UPDATE content_items SET status='approved', approved_by='usr_admin',
                   updated_at=? WHERE id=?""",
                (now_iso(), item_id),
            )
            self._audit(
                conn,
                item["organization_id"],
                item["company_id"],
                "usr_admin",
                "content.approved",
                "content",
                item_id,
                {},
            )

    def schedule_content(self, item_id: str, scheduled_for: str) -> None:
        with self.connect() as conn:
            item = conn.execute(
                """SELECT content_items.*, companies.organization_id
                   FROM content_items JOIN companies ON companies.id=content_items.company_id
                   WHERE content_items.id=?""",
                (item_id,),
            ).fetchone()
            if not item or item["status"] != "approved":
                return
            conn.execute(
                """UPDATE content_items SET status='scheduled', scheduled_for=?,
                   updated_at=? WHERE id=?""",
                (scheduled_for, now_iso(), item_id),
            )
            self._audit(
                conn,
                item["organization_id"],
                item["company_id"],
                "usr_admin",
                "content.scheduled",
                "content",
                item_id,
                {"scheduled_for": scheduled_for, "bounded_autonomy": True},
            )

    def invite(self, email: str, role: str = "creator") -> tuple[str, str]:
        invite_id, token = new_id("inv"), secrets.token_urlsafe(24)
        with self.connect() as conn:
            org = conn.execute("SELECT id FROM organizations LIMIT 1").fetchone()
            conn.execute(
                """INSERT INTO invitations VALUES (?, ?, ?, ?, ?, 'pending', 'usr_admin',
                   ?, ?)""",
                (
                    invite_id,
                    org["id"],
                    email.lower().strip(),
                    role,
                    hashlib.sha256(token.encode()).hexdigest(),
                    (datetime.now(UTC) + timedelta(days=7)).isoformat(),
                    now_iso(),
                ),
            )
            self._audit(
                conn,
                org["id"],
                None,
                "usr_admin",
                "team.invited",
                "invitation",
                invite_id,
                {"email": email, "role": role, "delivery": "pending_postmark"},
            )
        return invite_id, token

    @staticmethod
    def _audit(
        conn: sqlite3.Connection,
        organization_id: str,
        company_id: str | None,
        actor_id: str | None,
        event_type: str,
        object_type: str | None,
        object_id: str | None,
        details: dict,
    ) -> None:
        conn.execute(
            """INSERT INTO audit_events
               (organization_id, company_id, actor_id, event_type, object_type,
                object_id, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                organization_id,
                company_id,
                actor_id,
                event_type,
                object_type,
                object_id,
                json.dumps(details),
                now_iso(),
            ),
        )


store = Store()
