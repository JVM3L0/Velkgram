import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from tests.fakes.bot_client import FakeBotClient, FakeMonotonic
from tests.fakes.clock import FakeClock
from tests.fakes.messages import NOW, msg
from tests.fakes.notifier import FakeNotifier
from tests.fakes.telegram import FakeTelegramGateway
from velkgram.alerting import Alert, AlertKind, AlertStatus
from velkgram.alerting.adapters.notify_telegram import TelegramBotNotifier
from velkgram.alerting.adapters.sqlite.notifier_state import SqliteNotifierStateStore
from velkgram.alerting.adapters.sqlite.repository import SqliteAlertRepository
from velkgram.alerting.ports.notifier_state import NotifierStatus
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.apps.collector.collector import Collector
from velkgram.apps.notifier_wiring import ChatHolder
from velkgram.channels import ChannelCommands, ChannelStatus
from velkgram.channels.adapters.sqlite.repository import SqliteChannelRepository
from velkgram.ingestion import ResolvedChannel, TelegramDeferred
from velkgram.ingestion.adapters.sqlite.repository import SqliteMessageRepository
from velkgram.shared.adapters.bus_memory import MemoryBus
from velkgram.shared.db import connect
from velkgram.shared.events import ChannelsChanged, WishlistChanged
from velkgram.shared.migrate import apply_migrations
from velkgram.wishlist import WishCommands
from velkgram.wishlist.adapters.sqlite.repository import SqliteWishRepository

CH = -1001234567890
RES = {"@loja": ResolvedChannel(CH, "Loja")}


async def _nosleep(_s: float) -> None:
    return None


LIVE_COLLECTORS: list[Collector] = []  # stopped by tests/apps/conftest.py at teardown


class Env:
    def __init__(self, tmp_path: Path, gateway: FakeTelegramGateway | None = None) -> None:
        self.path = tmp_path / "v.db"
        self.conn = connect(self.path)
        self.clock = FakeClock(NOW)
        self.gateway = gateway or FakeTelegramGateway({}, dict(RES))
        self.notifier = FakeNotifier()
        self.bus = MemoryBus()
        apply_migrations(self.conn, MIGRATION_PACKAGES)
        self.collector = self.build()

    def build(self) -> Collector:
        self.bus = MemoryBus()
        c = Collector(self.conn, self.gateway, self.notifier, self.clock, self.bus, _nosleep)
        self.collector = c
        LIVE_COLLECTORS.append(c)
        return c

    def channel(self, ref: str = "@loja") -> int:
        ch = ChannelCommands(SqliteChannelRepository(self.conn), self.clock).add(ref)
        assert ch.id is not None
        return ch.id

    def wish(self, name: str = "Teclado", term: str = "teclado") -> int:
        w = WishCommands(SqliteWishRepository(self.conn)).create(name, (term,), (), 50000)
        assert w.id is not None
        return w.id

    def count(self, table: str, where: str = "1=1") -> int:
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def _status(conn: sqlite3.Connection, id: int) -> tuple[str, str | None, int | None]:
    r = conn.execute("SELECT status, error, telegram_id FROM channels WHERE id=?", (id,)).fetchone()
    return r[0], r[1], r[2]


async def test_end_to_end_message_to_alert(env: Env) -> None:
    env.channel()
    env.wish()
    await env.collector.start()
    await env.collector.ingestor.on_new(msg(1, CH, "Teclado mecanico R$ 200"))
    await env.bus.drain()
    await env.collector.evaluator.wait_idle()
    assert env.count("alerts", "status='sent'") == 1
    assert env.notifier.sent[0].wish_name == "Teclado"
    assert env.notifier.sent[0].channel_name == "Loja"


async def test_disabled_wish_stops_alerting_after_reload(env: Env) -> None:
    env.channel()
    wid = env.wish()
    await env.collector.start()
    WishCommands(SqliteWishRepository(env.conn)).toggle(wid, False)
    await env.bus.publish(WishlistChanged(2))
    await env.bus.drain()
    await env.collector.ingestor.on_new(msg(1, CH, "Teclado R$ 200"))
    await env.bus.drain()
    await env.collector.wait_idle()
    assert env.notifier.sent == []


async def test_pending_channel_resolved_activated_and_backfilled(tmp_path: Path) -> None:
    gw = FakeTelegramGateway({CH: [msg(5, CH, "Teclado R$ 100")]}, dict(RES))
    env = Env(tmp_path, gw)
    cid = env.channel()
    env.wish()
    await env.collector.start()
    await env.bus.drain()
    await env.collector.wait_idle()
    assert _status(env.conn, cid) == ("active", None, CH)
    assert env.count("messages") == 1
    assert len(env.notifier.sent) == 1


async def test_new_channel_backfill_is_not_dropped(tmp_path: Path) -> None:
    gw = FakeTelegramGateway({CH: [msg(5, CH, "Teclado R$ 100")]}, dict(RES))
    env = Env(tmp_path, gw)
    env.wish()
    await env.collector.start()
    ChannelCommands(SqliteChannelRepository(env.conn), env.clock).add("@loja")
    await env.bus.publish(ChannelsChanged(9))
    await env.bus.drain()
    await env.collector.wait_idle()
    await env.bus.drain()
    await env.collector.wait_idle()
    assert env.count("messages", f"channel_id={CH}") == 1
    assert len(env.notifier.sent) == 1


class SlowGateway(FakeTelegramGateway):
    def __init__(self) -> None:
        super().__init__({}, dict(RES))
        self.release = asyncio.Event()

    async def resolve_and_join(self, ref: str) -> ResolvedChannel:
        await self.release.wait()
        return await super().resolve_and_join(ref)


async def test_slow_resolution_does_not_block_message_evaluation(tmp_path: Path) -> None:
    gw = SlowGateway()
    gw.resolutions["@nova"] = ResolvedChannel(-1009999999999, "Nova")
    env = Env(tmp_path, gw)
    env.channel("@nova")
    env.wish()
    gw.release.set()
    await env.collector.start()
    gw.release.clear()
    # a second, new pending channel whose resolution hangs
    ChannelCommands(SqliteChannelRepository(env.conn), env.clock).add("@loja")
    await env.bus.publish(ChannelsChanged(2))
    await asyncio.wait_for(env.bus.drain(), timeout=1)  # handler returns while resolve hangs
    await env.collector.ingestor.on_new(msg(1, -1009999999999, "Teclado R$ 100"))
    await asyncio.wait_for(env.bus.drain(), timeout=1)
    await env.collector.evaluator.wait_idle()
    assert len(env.notifier.sent) == 1
    gw.release.set()
    await env.collector.wait_idle()


async def test_unresolvable_channel_marked_error_with_reason(env: Env) -> None:
    cid = env.channel("@naoexiste")
    await env.collector.start()
    status, error, _ = _status(env.conn, cid)
    assert status == ChannelStatus.ERROR.value
    assert error == "Canal não encontrado: @naoexiste"


async def test_deferred_channel_stays_pending(tmp_path: Path) -> None:
    class Deferring(FakeTelegramGateway):
        async def resolve_and_join(self, ref: str) -> ResolvedChannel:
            raise TelegramDeferred(120)

    env = Env(tmp_path, Deferring({}, {}))
    cid = env.channel()
    await env.collector.start()
    assert _status(env.conn, cid)[0] == "pending"


async def test_fatal_notifies_once_and_marks_heartbeat(env: Env) -> None:
    env.channel()
    await env.collector.start()
    await env.collector.fatal("sessao revogada")
    assert len(env.notifier.system) == 1
    assert "sessao revogada" in env.notifier.system[0]
    assert env.collector.stopped
    hb = SqliteMessageRepository(env.conn, env.clock).read_heartbeat()
    assert hb is not None
    assert hb.connection_state == "fatal"
    assert hb.fatal_reason == "sessao revogada"
    await env.collector.ingestor.on_new(msg(1, CH, "Teclado"))
    assert env.count("messages") == 0


async def test_restart_does_not_duplicate_alerts(env: Env) -> None:
    env.channel()
    env.wish()
    await env.collector.start()
    m = msg(1, CH, "Teclado R$ 200")
    await env.collector.ingestor.on_new(m)
    await env.bus.drain()
    await env.collector.wait_idle()
    assert env.count("alerts") == 1
    second = env.build()
    await second.start()
    await second.ingestor.on_new(m)
    await env.bus.drain()
    await second.wait_idle()
    assert env.count("alerts") == 1
    assert len(env.notifier.sent) == 1


async def test_loop_entry_points_swallow_errors(env: Env) -> None:
    env.channel()
    await env.collector.start()

    async def boom(*_a: object, **_k: object) -> AsyncIterator[None]:
        raise RuntimeError("x")
        yield

    env.gateway.latest_message_id = boom  # type: ignore[method-assign,assignment]
    await env.collector.run_gap_check()
    await env.collector.run_retry_failed()
    await env.collector.housekeeping_tick()


async def test_duplicate_telegram_id_marks_second_channel_failed_and_start_completes(
    env: Env,
) -> None:
    env.gateway.resolutions["@dupl"] = ResolvedChannel(CH, "Loja de novo")
    first = env.channel("@loja")
    second = env.channel("@dupl")
    await env.collector.start()
    assert _status(env.conn, first) == ("active", None, CH)
    status, error, _ = _status(env.conn, second)
    assert status == ChannelStatus.ERROR.value
    assert error == "Canal já cadastrado"


async def test_unexpected_error_for_one_channel_does_not_stop_the_rest(env: Env) -> None:
    env.gateway.resolutions["@okay"] = ResolvedChannel(-1005555555555, "Ok")
    bad = env.channel("@loja")
    good = env.channel("@okay")
    original = env.gateway.resolve_and_join

    async def flaky(ref: str) -> ResolvedChannel:
        if ref == "@loja":
            raise RuntimeError("boom")
        return await original(ref)

    env.gateway.resolve_and_join = flaky  # type: ignore[method-assign]
    await env.collector.start()
    assert _status(env.conn, bad)[1] == "Erro ao ativar o canal"
    assert _status(env.conn, good)[0] == "active"


async def test_fatal_notifies_before_heartbeat(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    original_notify = env.notifier.notify_system

    async def notify(text: str) -> None:
        order.append("notify")
        await original_notify(text)

    def beat(*_a: object, **_k: object) -> None:
        order.append("beat")

    env.notifier.notify_system = notify  # type: ignore[method-assign]
    monkeypatch.setattr(env.collector.heartbeat, "beat", beat)
    await env.collector.fatal("x")
    assert order == ["notify", "beat"]


async def test_fatal_beat_failure_does_not_prevent_notify(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def beat(*_a: object, **_k: object) -> None:
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(env.collector.heartbeat, "beat", beat)
    await env.collector.fatal("x")
    assert len(env.notifier.system) == 1


async def test_fatal_is_idempotent(env: Env) -> None:
    await env.collector.fatal("x")
    await env.collector.fatal("y")
    assert len(env.notifier.system) == 1


def _active_channel_with_cursor(env: Env, cursor: int) -> None:
    cid = env.channel()
    ChannelCommands(SqliteChannelRepository(env.conn), env.clock).activate(cid, CH, "Loja")
    SqliteMessageRepository(env.conn, env.clock).set_cursor(CH, cursor)


async def test_live_message_before_startup_backfill_does_not_hide_offline_gap(
    tmp_path: Path,
) -> None:
    offline = [msg(6, CH, "Teclado R$ 100"), msg(7, CH, "Teclado R$ 110")]
    live = msg(9, CH, "Teclado R$ 90")
    holder: list[Env] = []

    class LiveDuringStart(FakeTelegramGateway):
        async def resolve_and_join(self, ref: str) -> ResolvedChannel:
            await holder[0].collector.ingestor.on_new(live)  # lands mid-start()
            return await super().resolve_and_join(ref)

    gw = LiveDuringStart({CH: [*offline, live]}, {"@outro": ResolvedChannel(-1007777777777, "O")})
    env = Env(tmp_path, gw)
    holder.append(env)
    env.wish()
    _active_channel_with_cursor(env, 5)
    env.channel("@outro")
    await env.collector.start()
    await env.bus.drain()
    await env.collector.wait_idle()
    await env.bus.drain()
    await env.collector.wait_idle()
    assert env.count("messages", f"channel_id={CH}") == 3
    assert env.count("alerts") == 3  # 6, 7 backfilled; 9 once (live + backfill dedup)


async def test_live_message_after_reconnect_does_not_hide_offline_gap(tmp_path: Path) -> None:
    gw = FakeTelegramGateway({CH: []}, {})
    env = Env(tmp_path, gw)
    env.wish()
    _active_channel_with_cursor(env, 5)
    await env.collector.start()
    gw.connected = False
    await env.collector.housekeeping_tick()  # disconnect detected: snapshot taken
    gw.messages[CH] = [msg(6, CH, "Teclado R$ 100"), msg(9, CH, "Teclado R$ 90")]
    await env.collector.ingestor.on_new(msg(9, CH, "Teclado R$ 90"))  # live after catch-up
    gw.connected = True
    await env.collector.housekeeping_tick()
    await env.bus.drain()
    await env.collector.wait_idle()
    await env.bus.drain()
    await env.collector.wait_idle()
    assert env.count("messages", f"channel_id={CH}") == 2
    assert env.count("alerts") == 2


async def test_gap_check_uses_pending_snapshot(tmp_path: Path) -> None:
    gw = FakeTelegramGateway({CH: [msg(6, CH, "Teclado R$ 100"), msg(9, CH, "Teclado R$ 90")]}, {})
    env = Env(tmp_path, gw)
    env.wish()
    _active_channel_with_cursor(env, 5)
    await env.collector.start()  # startup backfill consumes the snapshot
    assert env.count("messages", f"channel_id={CH}") == 2
    assert gw.iter_calls[0][1] == 5


_SHOPEE_COUPON = (
    "Cupom Shopee\n\nR$ 10 OFF em R$ 40: QIP98Q1ZXO\n\n-Resgate aqui: \n"
    "https://s.shopee.com.br/70GSVaUJxC\n\n-Anúncio"
)


async def test_live_coupon_after_a_matching_offer_produces_one_coupon_alert(env: Env) -> None:
    env.channel()
    env.wish()
    await env.collector.start()
    product = replace(
        msg(1, CH, "Teclado mecanico por R$ 99"),
        date=NOW - timedelta(hours=2),
        links=("https://s.shopee.com.br/prod",),
        source="backfill",
    )
    await env.collector.ingestor.on_new(product)
    await env.bus.drain()
    await env.collector.wait_idle()
    coupon = replace(
        msg(2, CH, _SHOPEE_COUPON),
        date=NOW - timedelta(minutes=1),
        links=("https://s.shopee.com.br/70GSVaUJxC",),
    )
    await env.collector.ingestor.on_new(coupon)
    await env.bus.drain()
    await env.collector.wait_idle()
    assert env.count("alerts", "kind='coupon' AND status='sent'") == 1
    [sent] = [m for m in env.notifier.sent if m.rendered is not None]
    assert sent.rendered is not None
    assert sent.rendered.startswith("🎟️ Cupom Shopee: QIP98Q1ZXO")
    assert 'Para "Teclado"' in sent.rendered
    assert "💰 R$ 99,00" in sent.rendered


async def test_stopping_the_collector_leaves_no_pending_workers(env: Env) -> None:
    env.channel()
    await env.collector.start()
    workers = [env.collector._offer_worker, env.collector._coupon_worker]
    assert all(w is not None and not w.done() for w in workers)
    await env.collector.stop_offer_worker()
    assert all(w is not None and w.done() for w in workers)


async def _seed_product_and_coupon(env: Env) -> None:
    env.channel()
    env.wish()
    await env.collector.start()
    product = replace(
        msg(1, CH, "Teclado mecanico por R$ 99"),
        date=NOW - timedelta(hours=2),
        links=("https://s.shopee.com.br/prod",),
        source="backfill",
    )
    await env.collector.ingestor.on_new(product)
    await _settle(env)
    await _post_coupon(env, 2)


async def _settle(env: Env) -> None:
    await env.bus.drain()
    await env.collector.wait_idle()


async def _post_coupon(env: Env, message_id: int) -> None:
    coupon = replace(
        msg(message_id, CH, _SHOPEE_COUPON),
        date=env.clock.now() - timedelta(minutes=1),
        links=("https://s.shopee.com.br/70GSVaUJxC",),
    )
    await env.collector.ingestor.on_new(coupon)
    await _settle(env)


async def test_same_coupon_two_days_later_is_suppressed_by_the_three_day_window(
    env: Env,
) -> None:
    await _seed_product_and_coupon(env)
    assert env.count("alerts", "kind='coupon'") == 1
    env.clock.advance(2 * 24 * 3600)
    fresh = replace(
        msg(4, CH, "Teclado mecanico por R$ 99"),
        date=env.clock.now() - timedelta(hours=2),
        links=("https://s.shopee.com.br/prod2",),
        source="backfill",
    )
    await env.collector.ingestor.on_new(fresh)
    await _settle(env)
    await _post_coupon(env, 3)
    assert env.count("alerts", "kind='coupon'") == 1
    assert env.count("alert_suppressions", "rule='wish_coupon'") == 1


async def test_failed_coupon_alert_is_retried_from_its_stored_payload(env: Env) -> None:
    env.notifier = FakeNotifier(fail_times=3)  # one full send_with_retry round
    env.collector = env.build()
    await _seed_product_and_coupon(env)
    assert env.count("alerts", "kind='coupon' AND status='failed'") == 1
    env.conn.execute("DELETE FROM messages")  # nothing to rebuild the text from
    env.conn.commit()
    await env.collector.run_retry_failed()
    assert env.count("alerts", "kind='coupon' AND status='sent'") == 1
    assert env.count("alerts", "status='expired'") == 0
    [sent] = env.notifier.sent
    assert sent.rendered is not None
    assert sent.rendered.startswith("🎟️ Cupom Shopee: QIP98Q1ZXO")


def test_coupon_alert_without_payload_is_expired_not_rebuilt(env: Env) -> None:
    alert = Alert(
        id=1,
        wish_id=1,
        channel_id=CH,
        message_id=2,
        price_cents=9900,
        price_unknown=False,
        dedup_keys=(),
        status=AlertStatus.failed,
        attempts=0,
        delayed_minutes=None,
        created_at=NOW,
        sent_at=None,
        latency_telegram_ms=0,
        latency_internal_ms=0,
        last_error=None,
        kind=AlertKind.coupon,
        payload=None,
    )
    assert env.collector.build_message(alert) is None


async def _over_max_alert_with_active_coupon(env: Env) -> None:
    env.channel()
    env.wish()  # max R$ 500
    await env.collector.start()
    await _post_coupon(env, 2)
    live = replace(
        msg(3, CH, "Teclado mecanico por R$ 600"),
        date=env.clock.now(),
        links=("https://s.shopee.com.br/prod",),
    )
    await env.collector.ingestor.on_new(live)
    await _settle(env)


async def test_over_max_offer_after_a_stored_coupon_alerts_with_the_suffix(env: Env) -> None:
    await _over_max_alert_with_active_coupon(env)
    assert env.count("alerts", "kind='offer' AND over_max=1 AND status='sent'") == 1
    [sent] = [m for m in env.notifier.sent if m.rendered is None]
    assert sent.over_max_cents == 50000


async def test_retry_of_an_over_max_alert_keeps_the_suffix(env: Env) -> None:
    await _over_max_alert_with_active_coupon(env)
    [alert] = [
        a
        for a in SqliteAlertRepository(env.conn).list_since(NOW - timedelta(days=1))
        if a.kind is AlertKind.offer
    ]
    assert alert.over_max
    rebuilt = env.collector.build_message(alert)
    assert rebuilt is not None
    assert rebuilt.over_max_cents == 50000
    assert rebuilt.coupon_lines == ()


# --- telegram bot notifier end to end -----------------------------------------------------


def _bot_env(env: Env, bot: FakeBotClient, chat: int | None = 777) -> TelegramBotNotifier:
    mono = FakeMonotonic()
    state = SqliteNotifierStateStore(env.conn)
    state.set(NotifierStatus.ERROR, "iniciando", env.clock.now())
    holder = ChatHolder(chat)
    notifier = TelegramBotNotifier(
        bot,
        "tok:SECRET",
        chat_id=lambda: holder.resolve(state),
        state=state,
        clock=env.clock,
        monotonic=mono,
        sleep=mono.sleep,
    )
    env.notifier = notifier  # type: ignore[assignment]
    env.build()
    return notifier


async def _post_offer(env: Env) -> None:
    env.channel()
    env.wish()
    await env.collector.start()
    await env.collector.ingestor.on_new(msg(1, CH, "Teclado mecanico R$ 200"))
    await env.bus.drain()
    await env.collector.evaluator.wait_idle()


async def test_offer_alert_reaches_the_fake_bot_at_the_resolved_chat(env: Env) -> None:
    bot = FakeBotClient()
    _bot_env(env, bot, chat=777)
    await _post_offer(env)
    assert env.count("alerts", "status='sent'") == 1
    assert [c for c, _t, _p in bot.sent] == [777]
    assert "Teclado" in bot.sent[0][1]
    row = SqliteNotifierStateStore(env.conn).get()
    assert row is not None and row[0] is NotifierStatus.OK


async def test_failing_bot_login_fails_the_alert_without_leaking_the_token(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    bot = FakeBotClient()
    bot.start_error = RuntimeError("login rejected tok:SECRET")
    _bot_env(env, bot)
    await _post_offer(env)
    assert env.count("alerts", "status='failed'") == 1
    row = SqliteNotifierStateStore(env.conn).get()
    assert row is not None and row[:2] == (NotifierStatus.ERROR, "RuntimeError")
    assert bot.sent == []
    for r in caplog.records:
        assert "SECRET" not in r.getMessage()
        assert "SECRET" not in str(r.__dict__)
        assert "SECRET" not in (caplog.handler.format(r) if caplog.handler else "")
