from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastfunnel.config import settings
from fastfunnel.domain.schema import DDL, SCHEMA_VERSION

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
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.executescript(DDL)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations VALUES (?, ?)",
                (SCHEMA_VERSION, now_iso()),
            )
            if conn.execute("SELECT 1 FROM organizations LIMIT 1").fetchone():
                self._refresh_demo_identity(conn)
            else:
                created = now_iso()
                org_id, company_id, user_id = (
                    "org_predictivelabs",
                    "co_predictivelabs",
                    "usr_admin",
                )
                conn.execute(
                    "INSERT INTO organizations VALUES (?, ?, ?, ?)",
                    (org_id, "Predictive Labs", "predictive-labs", created),
                )
                profile = {
                    "website": f"https://{settings.seed_domain}",
                    "industry": "AI-first platform consultancy",
                    "market": "Global",
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
                    (user_id, settings.admin_email, "Demo Admin", created),
                )
                conn.execute(
                    "INSERT INTO memberships VALUES (?, ?, ?)",
                    (org_id, user_id, "admin"),
                )
                self._audit(
                    conn,
                    org_id,
                    company_id,
                    user_id,
                    "workspace.seeded",
                    "company",
                    company_id,
                    profile,
                )
        from fastfunnel.domain.marketing import MarketingService

        MarketingService(self).seed()

    def default_company_id(self) -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM companies ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            raise LookupError("No company workspace exists")
        return row["id"]

    def company_for_user(self, email: str | None = None, company_id: str | None = None) -> dict:
        """Resolve a company only through an explicit tenant or user membership."""
        with self.connect() as conn:
            if company_id:
                if email:
                    row = conn.execute(
                        """SELECT companies.* FROM companies
                           JOIN memberships
                             ON memberships.organization_id=companies.organization_id
                           JOIN users ON users.id=memberships.user_id
                           WHERE companies.id=? AND lower(users.email)=lower(?)""",
                        (company_id, email),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT * FROM companies WHERE id=?", (company_id,)
                    ).fetchone()
            elif email:
                row = conn.execute(
                    """SELECT companies.* FROM companies
                       JOIN memberships ON memberships.organization_id=companies.organization_id
                       JOIN users ON users.id=memberships.user_id
                       WHERE lower(users.email)=lower(?)
                       ORDER BY companies.created_at LIMIT 1""",
                    (email,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM companies ORDER BY created_at LIMIT 1"
                ).fetchone()
        if not row:
            raise LookupError("No authorized company workspace")
        return dict(row)

    def ensure_user_workspace(
        self,
        email: str,
        display_name: str | None = None,
    ) -> tuple[dict, dict]:
        """Idempotently provision an isolated product workspace for an auth account."""
        normalized_email = (email or "").strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized_email):
            raise ValueError("A valid account email is required")
        display_name = (display_name or "").strip()[:120]
        local_part, domain = normalized_email.rsplit("@", 1)
        fallback_name = re.sub(r"[._+-]+", " ", local_part).strip().title()
        display_name = display_name or fallback_name or "Workspace Admin"
        token = hashlib.sha256(normalized_email.encode()).hexdigest()[:16]
        user_id = f"usr_{token}"
        organization_id = f"org_{token}"
        company_id = f"co_{token}"
        slug_base = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
        slug = f"{slug_base or 'workspace'}-{token[:8]}"
        created = now_iso()

        with self.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM users WHERE lower(email)=lower(?)",
                (normalized_email,),
            ).fetchone()
            if existing:
                membership = conn.execute(
                    """SELECT companies.* FROM companies
                       JOIN memberships
                         ON memberships.organization_id=companies.organization_id
                       WHERE memberships.user_id=?
                       ORDER BY companies.created_at LIMIT 1""",
                    (existing["id"],),
                ).fetchone()
                if membership:
                    return dict(membership), dict(existing)
                user_id = existing["id"]
            else:
                conn.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?)",
                    (user_id, normalized_email, display_name, created),
                )

            conn.execute(
                "INSERT OR IGNORE INTO organizations VALUES (?, ?, ?, ?)",
                (organization_id, f"{display_name} Workspace", slug, created),
            )
            profile = {
                "website": f"https://{domain}",
                "industry": "Digital marketing",
                "market": "Global",
                "approval_policy": "bounded_autonomy_admin_approval",
                "provisioned": "self_service",
            }
            conn.execute(
                """INSERT OR IGNORE INTO companies
                   (id, organization_id, name, domain, profile_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    company_id,
                    organization_id,
                    f"{display_name} Marketing",
                    domain,
                    json.dumps(profile),
                    created,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO memberships VALUES (?, ?, 'admin')",
                (organization_id, user_id),
            )
            self._audit(
                conn,
                organization_id,
                company_id,
                user_id,
                "workspace.provisioned",
                "company",
                company_id,
                {"source": "account_auth", "email_domain": domain},
            )

        from fastfunnel.domain.marketing import MarketingService

        MarketingService(self).seed_company(company_id)
        return self.company_for_user(normalized_email, company_id), self.user_for_email(
            normalized_email
        )

    def user_for_email(self, email: str | None = None) -> dict:
        with self.connect() as conn:
            if email:
                row = conn.execute(
                    "SELECT * FROM users WHERE lower(email)=lower(?)", (email,)
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM users ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            raise LookupError("No user exists")
        return dict(row)

    @staticmethod
    def _refresh_demo_identity(conn: sqlite3.Connection) -> None:
        """Keep existing local demo databases aligned with the public demo identity."""
        admin = conn.execute(
            "SELECT id FROM users WHERE lower(email)=lower(?)",
            (settings.admin_email,),
        ).fetchone()
        if not admin:
            return
        organization = conn.execute(
            """SELECT organizations.id FROM organizations
               JOIN memberships
                 ON memberships.organization_id=organizations.id
               WHERE memberships.user_id=?
               ORDER BY organizations.created_at LIMIT 1""",
            (admin["id"],),
        ).fetchone()
        company = (
            conn.execute(
                """SELECT id FROM companies WHERE organization_id=?
                   ORDER BY created_at LIMIT 1""",
                (organization["id"],),
            ).fetchone()
            if organization
            else None
        )
        if not organization or not company or not admin:
            return
        profile = {
            "website": f"https://{settings.seed_domain}",
            "industry": "AI-first platform consultancy",
            "market": "Global",
            "approval_policy": "bounded_autonomy_admin_approval",
        }
        conn.execute(
            "UPDATE organizations SET name=?, slug=? WHERE id=?",
            (settings.seed_company, "predictive-labs", organization["id"]),
        )
        conn.execute(
            "UPDATE companies SET name=?, domain=?, profile_json=? WHERE id=?",
            (settings.seed_company, settings.seed_domain, json.dumps(profile), company["id"]),
        )
        conn.execute(
            "UPDATE users SET email=?, display_name=? WHERE id=?",
            (settings.admin_email, "Demo Admin", admin["id"]),
        )

    def dashboard(self, company_id: str | None = None) -> dict:
        with self.connect() as conn:
            company = dict(
                conn.execute(
                    "SELECT * FROM companies WHERE id=COALESCE(?, id) ORDER BY created_at LIMIT 1",
                    (company_id,),
                ).fetchone()
            )
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

    def list_content(self, company_id: str | None = None) -> list[dict]:
        company_id = company_id or self.default_company_id()
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM content_items WHERE company_id=?
                   ORDER BY created_at DESC""",
                (company_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_content(
        self,
        title: str,
        body: str,
        channel: str,
        *,
        company_id: str | None = None,
        actor_id: str = "usr_admin",
    ) -> str:
        item_id = new_id("cnt")
        created = now_iso()
        company_id = company_id or self.default_company_id()
        with self.connect() as conn:
            company = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
            if not company:
                raise LookupError("Unknown company")
            conn.execute(
                """INSERT INTO content_items
                   (id, company_id, title, body, channel, status, created_by,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'review', ?, ?, ?)""",
                (item_id, company["id"], title, body, channel, actor_id, created, created),
            )
            self._audit(
                conn,
                company["organization_id"],
                company["id"],
                actor_id,
                "content.created",
                "content",
                item_id,
                {"channel": channel, "status": "review"},
            )
        return item_id

    def approve_content(
        self,
        item_id: str,
        *,
        company_id: str | None = None,
        reviewer_id: str = "usr_admin",
    ) -> None:
        company_id = company_id or self.default_company_id()
        with self.connect() as conn:
            item = conn.execute(
                """SELECT content_items.*, companies.organization_id
                   FROM content_items JOIN companies ON companies.id=content_items.company_id
                   WHERE content_items.id=? AND content_items.company_id=?""",
                (item_id, company_id),
            ).fetchone()
            if not item or item["status"] != "review":
                return
            conn.execute(
                """UPDATE content_items SET status='approved', approved_by=?,
                   updated_at=? WHERE id=? AND company_id=?""",
                (reviewer_id, now_iso(), item_id, company_id),
            )
            self._audit(
                conn,
                item["organization_id"],
                item["company_id"],
                reviewer_id,
                "content.approved",
                "content",
                item_id,
                {},
            )

    def schedule_content(
        self,
        item_id: str,
        scheduled_for: str,
        *,
        company_id: str | None = None,
        actor_id: str = "usr_admin",
    ) -> None:
        company_id = company_id or self.default_company_id()
        with self.connect() as conn:
            item = conn.execute(
                """SELECT content_items.*, companies.organization_id
                   FROM content_items JOIN companies ON companies.id=content_items.company_id
                   WHERE content_items.id=? AND content_items.company_id=?""",
                (item_id, company_id),
            ).fetchone()
            if not item or item["status"] != "approved":
                return
            conn.execute(
                """UPDATE content_items SET status='scheduled', scheduled_for=?,
                   updated_at=? WHERE id=? AND company_id=?""",
                (scheduled_for, now_iso(), item_id, company_id),
            )
            self._audit(
                conn,
                item["organization_id"],
                item["company_id"],
                actor_id,
                "content.scheduled",
                "content",
                item_id,
                {"scheduled_for": scheduled_for, "bounded_autonomy": True},
            )

    def reschedule_content(
        self,
        item_id: str,
        scheduled_for: str,
        *,
        company_id: str,
        actor_id: str,
    ) -> None:
        with self.connect() as conn:
            item = conn.execute(
                """SELECT content_items.*, companies.organization_id
                   FROM content_items JOIN companies
                     ON companies.id=content_items.company_id
                   WHERE content_items.id=? AND content_items.company_id=?""",
                (item_id, company_id),
            ).fetchone()
            if not item or item["status"] != "scheduled":
                raise LookupError("Scheduled content not found")
            membership = conn.execute(
                """SELECT 1 FROM memberships
                   WHERE organization_id=? AND user_id=?""",
                (item["organization_id"], actor_id),
            ).fetchone()
            if not membership:
                raise PermissionError("Workspace membership required")
            conn.execute(
                """UPDATE content_items SET scheduled_for=?, updated_at=?
                   WHERE id=? AND company_id=?""",
                (scheduled_for, now_iso(), item_id, company_id),
            )
            self._audit(
                conn,
                item["organization_id"],
                company_id,
                actor_id,
                "content.rescheduled",
                "content",
                item_id,
                {
                    "previous_scheduled_for": item["scheduled_for"],
                    "scheduled_for": scheduled_for,
                },
            )

    def invite(
        self,
        email: str,
        role: str = "creator",
        *,
        company_id: str | None = None,
        actor_id: str = "usr_admin",
    ) -> tuple[str, str]:
        invite_id, token = new_id("inv"), secrets.token_urlsafe(24)
        company_id = company_id or self.default_company_id()
        with self.connect() as conn:
            company = conn.execute(
                "SELECT * FROM companies WHERE id=?", (company_id,)
            ).fetchone()
            if not company:
                raise LookupError("Unknown company")
            conn.execute(
                """INSERT INTO invitations VALUES (?, ?, ?, ?, ?, 'pending', ?,
                   ?, ?)""",
                (
                    invite_id,
                    company["organization_id"],
                    email.lower().strip(),
                    role,
                    hashlib.sha256(token.encode()).hexdigest(),
                    actor_id,
                    (datetime.now(UTC) + timedelta(days=7)).isoformat(),
                    now_iso(),
                ),
            )
            self._audit(
                conn,
                company["organization_id"],
                company["id"],
                actor_id,
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
