import logging
import random
import threading
import time
import zlib
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from velkgram.offers.adapters.http import fetcher as fetcher_module
from velkgram.offers.adapters.http.fetcher import HttpxFetcher, configure_fetch_logging
from velkgram.offers.domain.links import FetchPlan
from velkgram.offers.ports.fetcher import HostPaused

PLAN = FetchPlan(follow=True, first_hop_only=False, body_budget=1000)
HTML = {"content-type": "text/html; charset=utf-8"}


def resolve_public(host: str) -> list[str]:
    return ["93.184.216.34"]


def make(handler: httpx.MockTransport | None, **kw: object) -> HttpxFetcher:
    client = httpx.Client(transport=handler, follow_redirects=False)
    return HttpxFetcher(client=client, resolve_host=resolve_public, **kw)  # type: ignore[arg-type]


def routes(table: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return table[str(request.url)]

    return httpx.MockTransport(handler)


def redirect(location: str, code: int = 302) -> httpx.Response:
    return httpx.Response(code, headers={"location": location})


def noop(url: str) -> None:
    return None


def fetch(f: HttpxFetcher, url: str, plan: FetchPlan = PLAN, budget: int = 77, before=noop):
    return f.fetch(url, plan, before, lambda _u: budget)


def test_redirect_forms_are_resolved() -> None:
    t = routes(
        {
            "https://a.com/x": redirect("https://b.com/y"),
            "https://b.com/y": redirect("/z"),
            "https://b.com/z": redirect("//c.com/w"),
            "https://c.com/w": httpx.Response(200, headers=HTML, text="<html>ok</html>"),
        }
    )
    out = fetch(make(t), "https://a.com/x")
    assert out.hops == (
        "https://a.com/x",
        "https://b.com/y",
        "https://b.com/z",
        "https://c.com/w",
    )
    assert out.final_url == "https://c.com/w"
    assert out.status == 200
    assert out.body == "<html>ok</html>"
    assert out.answered_by == "c.com"
    assert out.content_type == "text/html; charset=utf-8"


def test_stops_after_five_redirects() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return redirect(f"https://h.com/{len(calls)}")

    out = fetch(make(httpx.MockTransport(handler)), "https://h.com/0")
    assert out.status == "invalid"
    assert len(calls) == 6  # the link plus 5 redirects


def test_redirect_loop_is_invalid() -> None:
    t = routes(
        {"https://a.com/": redirect("https://b.com/"), "https://b.com/": redirect("https://a.com/")}
    )
    out = fetch(make(t), "https://a.com/")
    assert out.status == "invalid"
    assert out.hops == ("https://a.com/", "https://b.com/")


def test_non_http_scheme_is_invalid_and_never_throttled() -> None:
    seen: list[str] = []
    out = fetch(make(routes({})), "intent://scan#Intent;end", before=seen.append)
    assert out.status == "invalid"
    assert seen == []


def test_redirect_to_non_http_scheme_is_invalid() -> None:
    t = routes({"https://a.com/": redirect("intent://x#Intent;end")})
    out = fetch(make(t), "https://a.com/")
    assert out.status == "invalid"
    assert out.hops == ("https://a.com/",)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1/x", "http://10.0.0.5/x", "http://169.254.169.254/", "http://[::1]/"]
)
def test_non_global_literal_ip_is_invalid(url: str) -> None:
    seen: list[str] = []
    out = fetch(make(routes({})), url, before=seen.append)
    assert out.status == "invalid"
    assert seen == []


@pytest.mark.parametrize("ip", ["100.64.0.1", "::ffff:10.0.0.1", "224.0.0.1", "0.0.0.0"])
def test_hosts_resolving_to_non_global_ips_are_invalid(ip: str) -> None:
    f = HttpxFetcher(
        client=httpx.Client(transport=routes({})), resolve_host=lambda _h: ["93.184.216.34", ip]
    )
    assert fetch(f, "https://evil.example/").status == "invalid"


def test_redirect_to_private_host_is_invalid() -> None:
    t = routes({"https://a.com/": redirect("http://192.168.0.1/admin")})
    out = fetch(make(t), "https://a.com/")
    assert out.status == "invalid"
    assert out.hops == ("https://a.com/",)


def test_dns_failure_is_error() -> None:
    def boom(host: str) -> list[str]:
        raise OSError("nxdomain")

    f = HttpxFetcher(client=httpx.Client(transport=routes({})), resolve_host=boom)
    assert fetch(f, "https://nope.example/").status == "error"


def test_first_hop_only_returns_the_location_without_requesting_it() -> None:
    t = routes(
        {
            "https://s.click.aliexpress.com/e/_a": redirect(
                "https://pt.aliexpress.com/item/1.html?productId=1"
            )
        }
    )
    plan = FetchPlan(follow=False, first_hop_only=True, body_budget=0)
    out = fetch(make(t), "https://s.click.aliexpress.com/e/_a", plan)
    assert out.status == 302
    assert out.final_url == "https://pt.aliexpress.com/item/1.html?productId=1"
    assert out.hops == ("https://s.click.aliexpress.com/e/_a", out.final_url)
    assert out.answered_by == "s.click.aliexpress.com"
    assert out.body is None


def test_follow_false_returns_the_redirect_as_is() -> None:
    t = routes({"https://a.com/": redirect("https://b.com/")})
    plan = FetchPlan(follow=False, first_hop_only=False, body_budget=100)
    out = fetch(make(t), "https://a.com/", plan)
    assert out.status == 302
    assert out.hops == ("https://a.com/",)


def test_before_request_runs_once_per_hop_with_that_hops_url() -> None:
    t = routes(
        {
            "https://a.com/x?tag=1": redirect("https://b.com/y"),
            "https://b.com/y": httpx.Response(200, headers=HTML, text="hi"),
        }
    )
    seen: list[str] = []
    fetch(make(t), "https://a.com/x?tag=1", before=seen.append)
    assert seen == ["https://a.com/x?tag=1", "https://b.com/y"]


def test_host_paused_ends_as_paused() -> None:
    t = routes(
        {
            "https://a.com/": redirect("https://b.com/"),
            "https://b.com/": httpx.Response(200, headers=HTML, text="hi"),
        }
    )

    def before(url: str) -> None:
        if "b.com" in url:
            raise HostPaused

    out = fetch(make(t), "https://a.com/", before=before)
    assert out.status == "paused"
    assert out.hops == ("https://a.com/",)
    assert out.body is None


def test_budget_for_is_used_at_the_final_host_when_plan_has_none() -> None:
    t = routes(
        {
            "https://a.com/": redirect("https://b.com/"),
            "https://b.com/": httpx.Response(200, headers=HTML, text="x" * 500),
        }
    )
    asked: list[str] = []

    def budget(url: str) -> int:
        asked.append(url)
        return 100

    plan = FetchPlan(follow=True, first_hop_only=False, body_budget=None)
    out = make(t).fetch("https://a.com/", plan, noop, budget)
    assert asked == ["https://b.com/"]
    assert out.body == "x" * 100


def test_zero_budget_has_no_body() -> None:
    t = routes({"https://a.com/": httpx.Response(200, headers=HTML, text="hello")})
    plan = FetchPlan(follow=True, first_hop_only=False, body_budget=0)
    assert fetch(make(t), "https://a.com/", plan).body is None


def test_non_html_has_no_body() -> None:
    t = routes(
        {
            "https://a.com/": httpx.Response(
                200, headers={"content-type": "image/png"}, content=b"\x89PNG"
            )
        }
    )
    out = fetch(make(t), "https://a.com/")
    assert out.body is None
    assert out.content_type == "image/png"


def test_multibyte_cut_at_the_budget_does_not_raise() -> None:
    t = routes({"https://a.com/": httpx.Response(200, headers=HTML, content=("é" * 100).encode())})
    plan = FetchPlan(follow=True, first_hop_only=False, body_budget=5)
    out = fetch(make(t), "https://a.com/", plan)
    assert out.body is not None
    assert out.body.startswith("éé")
    assert out.body == "éé\ufffd"


def test_charset_comes_from_the_header_then_meta() -> None:
    latin = "<html>ação</html>".encode("latin-1")
    t = routes(
        {
            "https://h.com/": httpx.Response(
                200, headers={"content-type": "text/html; charset=iso-8859-1"}, content=latin
            ),
            "https://m.com/": httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b'<meta charset="iso-8859-1">' + latin,
            ),
        }
    )
    f = make(t)
    assert "ação" in (fetch(f, "https://h.com/").body or "")
    assert "ação" in (fetch(f, "https://m.com/").body or "")


@pytest.mark.parametrize("code", [403, 429])
def test_blocked_statuses_report_who_answered(code: int) -> None:
    t = routes(
        {
            "https://a.com/": redirect("https://magalu.example/p/1"),
            "https://magalu.example/p/1": httpx.Response(code, headers=HTML, text="denied"),
        }
    )
    out = fetch(make(t), "https://a.com/")
    assert out.status == code
    assert out.answered_by == "magalu.example"
    assert out.body is None


def test_timeout_is_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    out = fetch(make(httpx.MockTransport(handler)), "https://a.com/")
    assert out.status == "error"
    assert out.body is None


def test_chain_deadline_stops_the_chain() -> None:
    t = routes(
        {"https://a.com/": redirect("https://b.com/"), "https://b.com/": redirect("https://c.com/")}
    )
    ticks = iter(range(0, 1000, 20))
    f = make(t, monotonic=lambda: float(next(ticks)))
    out = fetch(f, "https://a.com/")
    assert out.status == "error"
    assert out.hops == ("https://a.com/",)


def test_request_headers() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, headers=HTML, text="x")

    fetch(make(httpx.MockTransport(handler)), "https://a.com/")
    assert seen["accept-encoding"] == "gzip, deflate"
    assert seen["accept-language"] == "pt-BR"
    assert "Mozilla" in seen["user-agent"]


@pytest.fixture
def restore_loggers() -> Iterator[None]:
    names = ("httpx", "httpcore")
    old = [logging.getLogger(n).level for n in names]
    yield
    for n, level in zip(names, old, strict=True):
        logging.getLogger(n).setLevel(level)


def test_no_log_record_carries_a_query_string(
    caplog: pytest.LogCaptureFixture, restore_loggers: None
) -> None:
    configure_fetch_logging()
    t = routes(
        {
            "https://a.com/x?tag=SECRET": redirect("https://b.com/y?tag=SECRET"),
            "https://b.com/y?tag=SECRET": httpx.Response(200, headers=HTML, text="hi"),
        }
    )
    with caplog.at_level(logging.INFO):
        fetch(make(t), "https://a.com/x?tag=SECRET")
    assert "SECRET" not in caplog.text
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


# --- real socket: closing the stream at the budget stops the server -------------------


def test_stream_is_closed_at_the_budget_over_a_real_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The only test that lets the SSRF guard accept loopback.
    monkeypatch.setattr(fetcher_module, "_is_global", lambda _ip: True)
    broken = threading.Event()
    rng = random.Random(7)
    words = ["oferta", "produto", "preço", "frete", "cupom", "loja", "desconto"]

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            comp = zlib.compressobj(wbits=31)
            try:
                for _ in range(2000):
                    text = " ".join(rng.choice(words) + str(rng.random()) for _ in range(800))
                    data = comp.compress(text.encode()) + comp.flush(zlib.Z_SYNC_FLUSH)
                    self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                    self.wfile.flush()
                    time.sleep(0.01)
            except (BrokenPipeError, ConnectionResetError):
                broken.set()

        def log_message(self, format: str, *args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = httpx.Client(trust_env=False)
    try:
        f = HttpxFetcher(client=client, resolve_host=lambda _h: ["127.0.0.1"])
        started = time.monotonic()
        plan = FetchPlan(follow=True, first_hop_only=False, body_budget=64 * 1024)
        out = f.fetch(f"http://127.0.0.1:{server.server_port}/", plan, noop, lambda _u: 0)
        assert time.monotonic() - started < 2
        assert out.status == 200
        assert out.body is not None
        assert 0 < len(out.body.encode()) <= 64 * 1024
        assert broken.wait(5)
    finally:
        server.shutdown()
        server.server_close()
        client.close()
