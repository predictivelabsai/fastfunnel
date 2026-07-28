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
    admin_email: str = os.getenv("FASTFUNNEL_ADMIN_EMAIL", "kaljuvee@gmail.com")
    seed_company: str = os.getenv("FASTFUNNEL_SEED_COMPANY", "Factorio")
    seed_domain: str = os.getenv("FASTFUNNEL_SEED_DOMAIN", "factorio.co.uk")
    postmark_token: str = os.getenv("POSTMARK_SERVER_TOKEN", "")
    base_url: str = os.getenv("FASTFUNNEL_BASE_URL", "http://127.0.0.1:5005")


settings = Settings()
