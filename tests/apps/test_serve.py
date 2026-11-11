import sys
import threading
import time

import pytest

from velkgram.apps.serve import port_from_env, serve_commands, supervise

PY = sys.executable


def _sleeper(seconds: float) -> list[str]:
    return [PY, "-c", f"import time; time.sleep({seconds})"]


def _exiter(code: int) -> list[str]:
    return [PY, "-c", f"raise SystemExit({code})"]


def test_serve_commands_run_collector_enricher_and_web_on_the_given_port() -> None:
    commands = serve_commands(port=1234)
    assert commands["collector"] == ["velkgram", "collector"]
    assert commands["enricher"] == ["velkgram", "enrich"]
    web = commands["web"]
    assert "--factory" in web
    assert "velkgram.apps.web.main:create_app" in web
    assert web[web.index("--port") + 1] == "1234"
    assert web[web.index("--host") + 1] == "0.0.0.0"
    assert "--proxy-headers" in web
    assert web[web.index("--forwarded-allow-ips") + 1] == "*"


def test_supervise_stops_everything_when_one_child_dies_and_returns_its_code() -> None:
    started = time.monotonic()
    code = supervise(
        {"a": _sleeper(30), "b": _exiter(3)},
        stop=threading.Event(),
        poll_seconds=0.05,
        grace_seconds=5,
    )
    assert code == 3
    assert time.monotonic() - started < 10


def test_supervise_treats_a_clean_exit_as_failure() -> None:
    code = supervise(
        {"a": _sleeper(30), "b": _exiter(0)},
        stop=threading.Event(),
        poll_seconds=0.05,
        grace_seconds=5,
    )
    assert code == 1


def test_supervise_returns_zero_when_asked_to_stop() -> None:
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    started = time.monotonic()
    code = supervise(
        {"a": _sleeper(30), "b": _sleeper(30)},
        stop=stop,
        poll_seconds=0.05,
        grace_seconds=5,
    )
    assert code == 0
    assert time.monotonic() - started < 10


def test_supervise_kills_a_child_that_ignores_sigterm_after_the_grace() -> None:
    stubborn = [
        PY,
        "-c",
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
    ]
    stop = threading.Event()
    threading.Timer(0.5, stop.set).start()
    started = time.monotonic()
    code = supervise({"a": stubborn}, stop=stop, poll_seconds=0.05, grace_seconds=1)
    assert code == 0
    assert time.monotonic() - started < 10


@pytest.mark.parametrize("raw", ["", "abc", "0", "70000"])
def test_port_from_env_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError, match="PORT"):
        port_from_env({"PORT": raw})


def test_port_from_env_defaults_to_8000_and_reads_port() -> None:
    assert port_from_env({}) == 8000
    assert port_from_env({"PORT": "8080"}) == 8080
