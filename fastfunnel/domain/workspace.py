"""Tenant model preferences and encrypted integration credential storage."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken

from fastfunnel.domain.store import Store, new_id, now_iso

SUPPORTED_MODEL_PROVIDERS = {"xai"}
DEFAULT_MODEL_PROVIDER = "xai"
DEFAULT_MODEL_NAME = "grok-4-1-fast-reasoning"
DEFAULT_MODEL_TEMPERATURE = 0.2
SECRET_PROVIDERS = {"arcade", "composio"}


@dataclass(frozen=True)
class ModelPreferences:
    provider: str
    model: str
    temperature: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class APITokenPrincipal:
    company_id: str
    organization_id: str
    actor_id: str


class WorkspaceConfiguration:
    def __init__(self, store: Store):
        self.store = store

    def model_preferences(self, company_id: str) -> ModelPreferences:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workspace_settings WHERE company_id=?",
                (company_id,),
            ).fetchone()
        if not row:
            return ModelPreferences(
                DEFAULT_MODEL_PROVIDER,
                DEFAULT_MODEL_NAME,
                DEFAULT_MODEL_TEMPERATURE,
            )
        return ModelPreferences(
            row["model_provider"],
            row["model_name"],
            float(row["model_temperature"]),
        )

    def save_model_preferences(
        self,
        *,
        company_id: str,
        actor_id: str,
        provider: str,
        model: str,
        temperature: float,
    ) -> ModelPreferences:
        provider = provider.strip().lower()
        model = model.strip()
        temperature = float(temperature)
        if provider not in SUPPORTED_MODEL_PROVIDERS:
            raise ValueError("Unsupported model provider")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{1,119}", model):
            raise ValueError("Invalid model name")
        if not 0 <= temperature <= 2:
            raise ValueError("Temperature must be between 0 and 2")
        timestamp = now_iso()
        with self.store.connect() as conn:
            company = conn.execute(
                "SELECT * FROM companies WHERE id=?", (company_id,)
            ).fetchone()
            self._require_admin(conn, company["organization_id"], actor_id)
            conn.execute(
                """INSERT INTO workspace_settings
                   (company_id, model_provider, model_name, model_temperature,
                    updated_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(company_id) DO UPDATE SET
                     model_provider=excluded.model_provider,
                     model_name=excluded.model_name,
                     model_temperature=excluded.model_temperature,
                     updated_by=excluded.updated_by,
                     updated_at=excluded.updated_at""",
                (
                    company_id,
                    provider,
                    model,
                    temperature,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            Store._audit(
                conn,
                company["organization_id"],
                company_id,
                actor_id,
                "workspace.model.updated",
                "workspace",
                company_id,
                {"provider": provider, "model": model, "temperature": temperature},
            )
        return self.model_preferences(company_id)

    @staticmethod
    def _require_admin(conn, organization_id: str, actor_id: str) -> None:
        membership = conn.execute(
            """SELECT role FROM memberships
               WHERE organization_id=? AND user_id=?""",
            (organization_id, actor_id),
        ).fetchone()
        if not membership or membership["role"] != "admin":
            raise PermissionError("Workspace administrator permission required")


class SecretVault:
    """Encrypt tenant provider keys; decrypted values never enter view models."""

    key_env = "FASTFUNNEL_ENCRYPTION_KEY"

    def __init__(self, store: Store):
        self.store = store

    def configured(self) -> bool:
        try:
            self._fernet()
        except RuntimeError:
            return False
        return True

    def save_provider_key(
        self,
        *,
        company_id: str,
        actor_id: str,
        provider: str,
        api_key: str,
    ) -> dict:
        provider = provider.strip().lower()
        api_key = api_key.strip()
        if provider not in SECRET_PROVIDERS:
            raise ValueError("Unsupported credential provider")
        if not 12 <= len(api_key) <= 4096:
            raise ValueError("API key length is invalid")
        ciphertext = self._fernet().encrypt(api_key.encode())
        fingerprint = hashlib.sha256(api_key.encode()).hexdigest()[:12]
        timestamp = now_iso()
        with self.store.connect() as conn:
            company = conn.execute(
                "SELECT * FROM companies WHERE id=?", (company_id,)
            ).fetchone()
            WorkspaceConfiguration._require_admin(
                conn, company["organization_id"], actor_id
            )
            conn.execute(
                """INSERT INTO integration_secrets
                   (id, company_id, provider, secret_name, ciphertext, fingerprint,
                    status, last_validated_at, created_by, updated_by, created_at, updated_at)
                   VALUES (?, ?, ?, 'api_key', ?, ?, 'validated', ?, ?, ?, ?, ?)
                   ON CONFLICT(company_id, provider, secret_name) DO UPDATE SET
                     ciphertext=excluded.ciphertext,
                     fingerprint=excluded.fingerprint,
                     status='validated',
                     last_validated_at=excluded.last_validated_at,
                     validation_error=NULL,
                     updated_by=excluded.updated_by,
                     updated_at=excluded.updated_at""",
                (
                    new_id("sec"),
                    company_id,
                    provider,
                    ciphertext,
                    fingerprint,
                    timestamp,
                    actor_id,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            Store._audit(
                conn,
                company["organization_id"],
                company_id,
                actor_id,
                "integration.credential.updated",
                "integration",
                provider,
                {"secret_name": "api_key", "fingerprint": fingerprint},
            )
        return self.provider_status(company_id, provider)

    def provider_key(self, company_id: str, provider: str) -> str | None:
        with self.store.connect() as conn:
            row = conn.execute(
                """SELECT ciphertext FROM integration_secrets
                   WHERE company_id=? AND provider=? AND secret_name='api_key'
                     AND status='validated'""",
                (company_id, provider),
            ).fetchone()
        if not row:
            return None
        try:
            return self._fernet().decrypt(row["ciphertext"]).decode()
        except InvalidToken as exc:
            raise RuntimeError("Stored credential cannot be decrypted") from exc

    def provider_status(self, company_id: str, provider: str) -> dict:
        with self.store.connect() as conn:
            row = conn.execute(
                """SELECT provider, fingerprint, status, last_validated_at, updated_at
                   FROM integration_secrets
                   WHERE company_id=? AND provider=? AND secret_name='api_key'""",
                (company_id, provider),
            ).fetchone()
        return (
            dict(row)
            if row
            else {
                "provider": provider,
                "fingerprint": "",
                "status": "not_configured",
                "last_validated_at": None,
                "updated_at": None,
            }
        )

    def delete_provider_key(
        self,
        *,
        company_id: str,
        actor_id: str,
        provider: str,
    ) -> None:
        with self.store.connect() as conn:
            company = conn.execute(
                "SELECT * FROM companies WHERE id=?", (company_id,)
            ).fetchone()
            WorkspaceConfiguration._require_admin(
                conn, company["organization_id"], actor_id
            )
            conn.execute(
                """DELETE FROM integration_secrets
                   WHERE company_id=? AND provider=? AND secret_name='api_key'""",
                (company_id, provider),
            )
            Store._audit(
                conn,
                company["organization_id"],
                company_id,
                actor_id,
                "integration.credential.deleted",
                "integration",
                provider,
                {"secret_name": "api_key"},
            )

    def _fernet(self) -> Fernet:
        value = os.getenv(self.key_env, "").strip()
        if not value:
            raise RuntimeError(f"{self.key_env} is not configured")
        try:
            return Fernet(value.encode())
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{self.key_env} is invalid") from exc


class ConnectionSecretVault(SecretVault):
    """Connection-scoped write-only secrets for database and source adapters."""

    def save(
        self,
        *,
        company_id: str,
        connection_id: str,
        actor_id: str,
        secret_name: str,
        value: str,
    ) -> str:
        value = value.strip()
        if not value or len(value) > 16384:
            raise ValueError("Credential value is invalid")
        timestamp = now_iso()
        fingerprint = hashlib.sha256(value.encode()).hexdigest()[:12]
        ciphertext = self._fernet().encrypt(value.encode())
        with self.store.connect() as conn:
            connection = conn.execute(
                """SELECT data_connections_v2.*, companies.organization_id
                   FROM data_connections_v2
                   JOIN companies ON companies.id=data_connections_v2.company_id
                   WHERE data_connections_v2.id=? AND data_connections_v2.company_id=?""",
                (connection_id, company_id),
            ).fetchone()
            if not connection:
                raise LookupError("Unknown data connection")
            WorkspaceConfiguration._require_admin(
                conn, connection["organization_id"], actor_id
            )
            conn.execute(
                """INSERT INTO connection_secrets
                   (id, connection_id, secret_name, ciphertext, fingerprint,
                    created_by, updated_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(connection_id, secret_name) DO UPDATE SET
                     ciphertext=excluded.ciphertext,
                     fingerprint=excluded.fingerprint,
                     updated_by=excluded.updated_by,
                     updated_at=excluded.updated_at""",
                (
                    new_id("csec"),
                    connection_id,
                    secret_name,
                    ciphertext,
                    fingerprint,
                    actor_id,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            Store._audit(
                conn,
                connection["organization_id"],
                company_id,
                actor_id,
                "data_connection.credential.updated",
                "data_connection",
                connection_id,
                {"secret_name": secret_name, "fingerprint": fingerprint},
            )
        return fingerprint

    def get(self, *, company_id: str, connection_id: str, secret_name: str) -> str:
        with self.store.connect() as conn:
            row = conn.execute(
                """SELECT connection_secrets.ciphertext
                   FROM connection_secrets
                   JOIN data_connections_v2
                     ON data_connections_v2.id=connection_secrets.connection_id
                   WHERE connection_secrets.connection_id=?
                     AND connection_secrets.secret_name=?
                     AND data_connections_v2.company_id=?""",
                (connection_id, secret_name, company_id),
            ).fetchone()
        if not row:
            raise LookupError("Connection credential is not configured")
        try:
            return self._fernet().decrypt(row["ciphertext"]).decode()
        except InvalidToken as exc:
            raise RuntimeError("Stored connection credential cannot be decrypted") from exc


class APITokenService:
    """Issue revocable, tenant-bound API bearer tokens stored only as hashes."""

    def __init__(self, store: Store):
        self.store = store

    def issue(
        self,
        *,
        company_id: str,
        actor_id: str,
        label: str,
        lifetime_days: int = 90,
    ) -> tuple[str, dict]:
        label = label.strip()
        lifetime_days = int(lifetime_days)
        if not 3 <= len(label) <= 80:
            raise ValueError("Token label must contain 3 to 80 characters")
        if not 1 <= lifetime_days <= 365:
            raise ValueError("Token lifetime must be between 1 and 365 days")
        token = f"ff_live_{secrets.token_urlsafe(32)}"
        digest = hashlib.sha256(token.encode()).hexdigest()
        fingerprint = digest[:12]
        created_at = now_iso()
        expires_at = (
            datetime.now(UTC) + timedelta(days=lifetime_days)
        ).isoformat()
        token_id = new_id("tok")
        with self.store.connect() as conn:
            company = conn.execute(
                "SELECT * FROM companies WHERE id=?", (company_id,)
            ).fetchone()
            if not company:
                raise LookupError("Unknown company")
            WorkspaceConfiguration._require_admin(
                conn, company["organization_id"], actor_id
            )
            conn.execute(
                """INSERT INTO api_tokens
                   (id, company_id, label, token_hash, fingerprint, actor_id,
                    expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    token_id,
                    company_id,
                    label,
                    digest,
                    fingerprint,
                    actor_id,
                    expires_at,
                    created_at,
                ),
            )
            Store._audit(
                conn,
                company["organization_id"],
                company_id,
                actor_id,
                "api_token.created",
                "api_token",
                token_id,
                {
                    "label": label,
                    "fingerprint": fingerprint,
                    "expires_at": expires_at,
                },
            )
        return token, self.get(company_id, token_id)

    def authenticate(self, token: str) -> APITokenPrincipal | None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        timestamp = now_iso()
        with self.store.connect() as conn:
            row = conn.execute(
                """SELECT api_tokens.*, companies.organization_id
                   FROM api_tokens JOIN companies
                     ON companies.id=api_tokens.company_id
                   WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?""",
                (digest, timestamp),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE api_tokens SET last_used_at=? WHERE id=?",
                (timestamp, row["id"]),
            )
        return APITokenPrincipal(
            company_id=row["company_id"],
            organization_id=row["organization_id"],
            actor_id=row["actor_id"],
        )

    def list(self, company_id: str) -> list[dict]:
        with self.store.connect() as conn:
            rows = conn.execute(
                """SELECT id, label, fingerprint, actor_id, expires_at,
                          last_used_at, revoked_at, created_at
                   FROM api_tokens WHERE company_id=?
                   ORDER BY created_at DESC""",
                (company_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, company_id: str, token_id: str) -> dict:
        with self.store.connect() as conn:
            row = conn.execute(
                """SELECT id, label, fingerprint, actor_id, expires_at,
                          last_used_at, revoked_at, created_at
                   FROM api_tokens WHERE company_id=? AND id=?""",
                (company_id, token_id),
            ).fetchone()
        if not row:
            raise LookupError("Unknown API token")
        return dict(row)

    def revoke(
        self,
        *,
        company_id: str,
        actor_id: str,
        token_id: str,
    ) -> None:
        timestamp = now_iso()
        with self.store.connect() as conn:
            company = conn.execute(
                "SELECT * FROM companies WHERE id=?", (company_id,)
            ).fetchone()
            if not company:
                raise LookupError("Unknown company")
            WorkspaceConfiguration._require_admin(
                conn, company["organization_id"], actor_id
            )
            row = conn.execute(
                """SELECT * FROM api_tokens
                   WHERE id=? AND company_id=? AND revoked_at IS NULL""",
                (token_id, company_id),
            ).fetchone()
            if not row:
                raise LookupError("Active API token not found")
            conn.execute(
                "UPDATE api_tokens SET revoked_at=? WHERE id=?",
                (timestamp, token_id),
            )
            Store._audit(
                conn,
                company["organization_id"],
                company_id,
                actor_id,
                "api_token.revoked",
                "api_token",
                token_id,
                {"fingerprint": row["fingerprint"]},
            )
