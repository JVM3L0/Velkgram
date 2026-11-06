"""httpx link fetcher: manual redirects, per-host body budgets and an SSRF guard (spec §5.2).

The adapter logs nothing: links carry affiliate tokens in their query strings.
"""

import ipaddress
import logging
import re
import socket
import time
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from velkgram.offers.domain.links import FetchOutcome, FetchPlan, Status
from velkgram.offers.ports.fetcher import HostPaused

MAX_REDIRECTS = 5
REQUEST_TIMEOUT = 10.0
CHAIN_TIMEOUT = 30.0
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR",
    "Accept-Encoding": "gzip, deflate",
}
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([\w.:-]+)""", re.IGNORECASE)


def _getaddrinfo(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)]


def configure_fetch_logging() -> None:
    """httpx logs every request URL at INFO, query string included."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _is_global(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _decode(raw: bytes, content_type: str) -> str:
    charset = None
    m = re.search(r"charset\s*=\s*[\"']?([\w.:-]+)", content_type, re.IGNORECASE)
    if m:
        charset = m.group(1)
    elif (meta := _META_CHARSET.search(raw[:4096])) is not None:
        charset = meta.group(1).decode("ascii", errors="ignore")
    try:
        return raw.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


class _Chain:
    """Mutable state of one fetch; turned into a FetchOutcome at the end."""

    def __init__(self, url: str) -> None:
        self.hops: list[str] = []
        self.visited: set[str] = set()
        self.current = url
        self.answered_by = _host(url)

    def outcome(
        self, status: Status, content_type: str | None = None, body: str | None = None
    ) -> FetchOutcome:
        return FetchOutcome(
            self.hops[-1] if self.hops else self.current,
            tuple(self.hops),
            status,
            content_type,
            body,
            self.answered_by,
        )


class HttpxFetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        resolve_host: Callable[[str], list[str]] = _getaddrinfo,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client or httpx.Client(follow_redirects=False)
        self._resolve = resolve_host
        self._monotonic = monotonic

    def _is_safe_target(self, url: str) -> bool | None:
        """True: ok; False: invalid scheme or non-global IP; None: DNS failed."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        host = parts.hostname
        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            try:
                addresses = self._resolve(host)
            except OSError:
                return None
        return bool(addresses) and all(_is_global(a) for a in addresses)

    def fetch(
        self,
        url: str,
        plan: FetchPlan,
        before_request: Callable[[str], None],
        budget_for: Callable[[str], int],
    ) -> FetchOutcome:
        chain = _Chain(url)
        deadline = self._monotonic() + CHAIN_TIMEOUT
        try:
            return self._follow(chain, plan, before_request, budget_for, deadline)
        except (httpx.HTTPError, httpx.InvalidURL, ValueError):
            return chain.outcome("error")

    def _follow(
        self,
        chain: _Chain,
        plan: FetchPlan,
        before_request: Callable[[str], None],
        budget_for: Callable[[str], int],
        deadline: float,
    ) -> FetchOutcome:
        redirects = 0
        while True:
            current = chain.current
            if current in chain.visited:
                return chain.outcome("invalid")
            safe = self._is_safe_target(current)
            if safe is None:
                return chain.outcome("error")
            if not safe:
                return chain.outcome("invalid")
            if self._monotonic() > deadline:
                return chain.outcome("error")
            try:
                before_request(current)
            except HostPaused:
                return chain.outcome("paused")
            chain.visited.add(current)
            chain.hops.append(current)
            chain.answered_by = _host(current)
            with self._client.stream(
                "GET",
                current,
                headers=_HEADERS,
                timeout=REQUEST_TIMEOUT,
                follow_redirects=False,
            ) as response:
                location = response.headers.get("location")
                if response.is_redirect and location:
                    target = urljoin(current, location)
                    if plan.first_hop_only:
                        chain.hops.append(target)
                        return chain.outcome(response.status_code)
                    if not plan.follow:
                        return chain.outcome(response.status_code)
                    if redirects >= MAX_REDIRECTS:
                        return chain.outcome("invalid")
                    redirects += 1
                    chain.current = target
                    continue
                budget = plan.body_budget if plan.body_budget is not None else budget_for(current)
                return self._finish(chain, response, budget, deadline)

    def _finish(
        self, chain: _Chain, response: httpx.Response, budget: int, deadline: float
    ) -> FetchOutcome:
        content_type = response.headers.get("content-type")
        is_html = content_type is not None and content_type.lower().startswith("text/html")
        if budget <= 0 or not is_html or response.status_code >= 400:
            return chain.outcome(response.status_code, content_type)
        raw = bytearray()
        for piece in response.iter_bytes():
            raw += piece
            if len(raw) >= budget:
                break
            if self._monotonic() > deadline:
                return chain.outcome("error", content_type)
        text = _decode(bytes(raw[:budget]), content_type or "")
        return chain.outcome(response.status_code, content_type, text)
