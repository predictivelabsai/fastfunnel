"""Read-only PostgreSQL source connections and schema discovery."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fastfunnel.domain.store import Store, new_id, now_iso
from fastfunnel.domain.workspace import ConnectionSecretVault, WorkspaceConfiguration

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$-]{0,127}$")
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,252}$")


@dataclass(frozen=True)
class PostgresConnectionConfig:
    host: str
    port: int
    database: str
    username: str
    sslmode: str = "require"
    schemas: tuple[str, ...] = ("public",)

    def validated(self) -> PostgresConnectionConfig:
        if not _HOST.fullmatch(self.host):
            raise ValueError("Invalid PostgreSQL host")
        if not 1 <= int(self.port) <= 65535:
            raise ValueError("Invalid PostgreSQL port")
        if not _NAME.fullmatch(self.database) or not _NAME.fullmatch(self.username):
            raise ValueError("Invalid PostgreSQL database or username")
        if self.sslmode not in {"disable", "require", "verify-ca", "verify-full"}:
            raise ValueError("Unsupported PostgreSQL SSL mode")
        if not self.schemas or any(not _NAME.fullmatch(name) for name in self.schemas):
            raise ValueError("At least one valid schema is required")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": int(self.port),
            "database": self.database,
            "username": self.username,
            "sslmode": self.sslmode,
            "schemas": list(self.schemas),
        }


class PostgresInspector:
    def __init__(self, connect: Callable[..., Any] = psycopg.connect):
        self.connect = connect

    def inspect(
        self,
        config: PostgresConnectionConfig,
        password: str,
    ) -> dict[str, Any]:
        config.validated()
        with self.connect(
            host=config.host,
            port=config.port,
            dbname=config.database,
            user=config.username,
            password=password,
            sslmode=config.sslmode,
            connect_timeout=8,
            options="-c default_transaction_read_only=on -c statement_timeout=5000",
            row_factory=dict_row,
        ) as connection:
            read_only = connection.execute(
                "SHOW default_transaction_read_only"
            ).fetchone()["default_transaction_read_only"]
            rows = connection.execute(
                """SELECT table_schema, table_name, table_type
                   FROM information_schema.tables
                   WHERE table_schema = ANY(%s)
                   ORDER BY table_schema, table_name
                   LIMIT 500""",
                (list(config.schemas),),
            ).fetchall()
        return {
            "read_only": str(read_only).lower() in {"on", "true", "1"},
            "objects": [dict(row) for row in rows],
        }


class PostgresConnectionService:
    def __init__(self, store: Store, inspector: PostgresInspector | None = None):
        self.store = store
        self.inspector = inspector or PostgresInspector()
        self.vault = ConnectionSecretVault(store)

    def save_and_verify(
        self,
        *,
        company_id: str,
        actor_id: str,
        name: str,
        config: PostgresConnectionConfig,
        password: str,
    ) -> dict[str, Any]:
        name = name.strip()
        if not 3 <= len(name) <= 100:
            raise ValueError("Connection name must contain 3 to 100 characters")
        config.validated()
        result = self.inspector.inspect(config, password)
        if not result["read_only"]:
            raise PermissionError("PostgreSQL role must default to read-only")
        connection_id = new_id("dcon")
        timestamp = now_iso()
        with self.store.connect() as conn:
            company = conn.execute(
                "SELECT organization_id FROM companies WHERE id=?", (company_id,)
            ).fetchone()
            if not company:
                raise LookupError("Unknown workspace")
            WorkspaceConfiguration._require_admin(
                conn, company["organization_id"], actor_id
            )
            existing = conn.execute(
                """SELECT id FROM data_connections_v2
                   WHERE company_id=? AND name=?""",
                (company_id, name),
            ).fetchone()
            connection_id = existing["id"] if existing else connection_id
            conn.execute(
                """INSERT INTO data_connections_v2
                   (id, company_id, provider, name, mode, status, config_json,
                    last_checked_at, created_by, created_at, updated_at)
                   VALUES (?, ?, 'postgres', ?, 'read_only', 'connected', ?, ?, ?, ?, ?)
                   ON CONFLICT(company_id, name) DO UPDATE SET
                     provider='postgres', mode='read_only', status='connected',
                     config_json=excluded.config_json,
                     last_checked_at=excluded.last_checked_at,
                     last_error=NULL, updated_at=excluded.updated_at""",
                (
                    connection_id,
                    company_id,
                    name,
                    json.dumps(config.public_dict()),
                    timestamp,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
        fingerprint = self.vault.save(
            company_id=company_id,
            connection_id=connection_id,
            actor_id=actor_id,
            secret_name="password",
            value=password,
        )
        return {
            "id": connection_id,
            "name": name,
            "status": "connected",
            "fingerprint": fingerprint,
            "object_count": len(result["objects"]),
        }

    def list(self, company_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute(
                """SELECT id, provider, name, mode, status, config_json,
                          last_checked_at, last_error
                   FROM data_connections_v2 WHERE company_id=?
                   ORDER BY name""",
                (company_id,),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["config"] = json.loads(item.pop("config_json"))
            output.append(item)
        return output
