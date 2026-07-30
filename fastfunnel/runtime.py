"""Production process supervisor for the web application and durable worker."""

from __future__ import annotations

import signal
import subprocess
import sys
import time


def main() -> None:
    commands = (
        (sys.executable, "-m", "fastfunnel.app"),
        (sys.executable, "-m", "fastfunnel.worker"),
    )
    processes = [subprocess.Popen(command) for command in commands]

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


if __name__ == "__main__":
    main()
