"""Production process supervisor for the web application and durable worker."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fastfunnel.config import settings


def cloud_sql_proxy() -> tuple[subprocess.Popen | None, Path | None]:
    if not settings.cloud_sql_instance:
        return None, None
    raw_credentials = os.getenv(
        "TENDLY_GOOGLE_APPLICATION_CREDENTIALS_JSON", ""
    ).strip()
    if not raw_credentials:
        raise RuntimeError(
            "TENDLY_GOOGLE_APPLICATION_CREDENTIALS_JSON is required for the proxy"
        )
    try:
        credentials = json.loads(raw_credentials)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Tendly Cloud SQL credentials are invalid") from exc
    if not isinstance(credentials, dict) or not credentials.get("client_email"):
        raise RuntimeError("Tendly Cloud SQL credentials are incomplete")
    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix="fastfunnel-cloudsql-",
        suffix=".json",
        delete=False,
    ) as handle:
        credential_path = Path(handle.name)
        json.dump(credentials, handle)
    try:
        credential_path.chmod(0o600)
        process = subprocess.Popen(
            (
                "/usr/local/bin/cloud-sql-proxy",
                "--address",
                "127.0.0.1",
                "--port",
                str(settings.cloud_sql_port),
                "--credentials-file",
                str(credential_path),
                settings.cloud_sql_instance,
            ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return process, credential_path
    except Exception:
        credential_path.unlink(missing_ok=True)
        raise


def main() -> None:
    commands = (
        (sys.executable, "-m", "fastfunnel.app"),
        (sys.executable, "-m", "fastfunnel.worker"),
    )
    proxy, credential_path = cloud_sql_proxy()
    processes = [subprocess.Popen(command) for command in commands]
    if proxy:
        processes.append(proxy)

    def stop_children(_signum, _frame) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop_children)
    signal.signal(signal.SIGINT, stop_children)
    try:
        while True:
            exited = next(
                (process for process in processes if process.poll() is not None),
                None,
            )
            if exited:
                exit_code = exited.returncode or 1
                stop_children(signal.SIGTERM, None)
                for process in processes:
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                raise SystemExit(exit_code)
            time.sleep(0.5)
    finally:
        stop_children(signal.SIGTERM, None)
        if credential_path:
            credential_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
