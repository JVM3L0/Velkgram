"""Single-container runner: migrate, then collector + web under one supervisor.

Railway volumes attach to one service only, and the three processes share one SQLite file,
so on Railway they run side by side in the same container. The link enricher and the post-image
sync are threads of the collector process (woken by `OfferCreated`), not children of their own.
If any child dies, the others are stopped and the container exits non-zero so the platform
restarts it.
"""

import os
import signal
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence

DEFAULT_PORT = 8000
GRACE_SECONDS = 40.0  # below the compose 45 s grace; Railway allows ~60 s


def port_from_env(env: Mapping[str, str]) -> int:
    raw = env.get("PORT")
    if raw is None:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(f"PORT must be an integer: {raw!r}") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"PORT out of range: {port}")
    return port


def serve_commands(port: int) -> dict[str, list[str]]:
    return {
        "collector": ["velkgram", "collector"],
        "web": [
            sys.executable,
            "-m",
            "uvicorn",
            "--factory",
            "velkgram.apps.web.main:create_app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
            "--proxy-headers",
            "--forwarded-allow-ips",
            "*",
        ],
    }


def _terminate(procs: Mapping[str, subprocess.Popen[bytes]], grace_seconds: float) -> None:
    for proc in procs.values():
        if proc.poll() is None:
            proc.terminate()
    for proc in procs.values():
        try:
            proc.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def supervise(
    commands: Mapping[str, Sequence[str]],
    *,
    stop: threading.Event,
    poll_seconds: float = 1.0,
    grace_seconds: float = GRACE_SECONDS,
) -> int:
    """Run all commands; return 0 when asked to stop, else the exit code of the first to die."""
    procs = {name: subprocess.Popen(list(argv)) for name, argv in commands.items()}
    code = 0
    try:
        while not stop.wait(poll_seconds):
            dead = {n: p.returncode for n, p in procs.items() if p.poll() is not None}
            if dead:
                # A long-running service exiting, even cleanly, is a failure to restart from.
                code = next(iter(dead.values())) or 1
                break
    finally:
        _terminate(procs, grace_seconds)
    return code


def serve() -> int:
    migrated = subprocess.run(["velkgram", "migrate"], check=False)
    if migrated.returncode != 0:
        return migrated.returncode
    stop = threading.Event()
    previous = {
        sig: signal.signal(sig, lambda _signum, _frame: stop.set())
        for sig in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        return supervise(serve_commands(port_from_env(os.environ)), stop=stop)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
