from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path(
        os.getenv("FASTFUNNEL_DB_PATH", str(ROOT / "data" / "fastfunnel.sqlite3"))
    )
    host: str = os.getenv("FASTFUNNEL_HOST", "127.0.0.1")
    port: int = int(os.getenv("FASTFUNNEL_PORT", "5005"))
    dev_auth_bypass: bool = os.getenv("FASTFUNNEL_DEV_AUTH_BYPASS", "1") == "1"
    admin_email: str = os.getenv("FASTFUNNEL_ADMIN_EMAIL", "admin@fastfunnel.app")
    seed_company: str = os.getenv("FASTFUNNEL_SEED_COMPANY", "Predictive Labs")
    seed_domain: str = os.getenv("FASTFUNNEL_SEED_DOMAIN", "predictivelabs.ai")
    postmark_token: str = os.getenv(
        "POSTMARK_SERVER_TOKEN",
        os.getenv("POSTMARK_API_TOKEN", ""),
    )
    base_url: str = os.getenv("FASTFUNNEL_BASE_URL", "http://127.0.0.1:5005")
    seed_businesses: bool = os.getenv("FASTFUNNEL_SEED_BUSINESSES", "0") == "1"
    platform_database_url: str = os.getenv("FASTFUNNEL_DATABASE_URL", "").strip()
    cloud_sql_instance: str = os.getenv("TENDLY_CLOUD_SQL_INSTANCE", "").strip()
    cloud_sql_port: int = int(os.getenv("TENDLY_CLOUD_SQL_PROXY_PORT", "5434"))
    portfolio_admin_emails: tuple[str, ...] = tuple(
        value.strip().lower()
        for value in os.getenv("FASTFUNNEL_PORTFOLIO_ADMIN_EMAILS", "").split(",")
        if value.strip()
    )


settings = Settings()
