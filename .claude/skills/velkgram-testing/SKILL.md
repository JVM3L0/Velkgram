---
name: velkgram-testing
description: Use when writing or running tests in Velkgram — TDD loop, which test layer to use (domain, services with fakes, adapter contracts, Telethon fixtures, web, architecture, latency), where fakes live, and the exact check commands that must pass before a task is done.
---

# Velkgram testing

TDD is mandatory: **red → green → refactor**. Write the failing test first, see it fail for the right reason, then implement. (For the full discipline, use `superpowers:test-driven-development`.)

## Pick the layer

| Testing… | Layer | Location | Uses |
|---|---|---|---|
| matching, pricing, dedup, normalization | domain | `tests/<module>/domain/` | plain functions, `pytest.mark.parametrize` tables |
| a use case (ingest, evaluate, notify, backfill, reprocess, retry) | services | `tests/<module>/services/` | fakes from `tests/fakes/` |
| a port implementation | contract | `tests/contracts/test_<port>.py` | one suite parametrized over every implementation |
| Telethon → `Message` mapping | adapter | `tests/ingestion/adapters/` | recorded fixtures in `tests/fixtures/telegram/` |
| pages, forms, login | web | `tests/<module>/web/` | FastAPI `TestClient` + temp SQLite |
| module boundaries | architecture | `lint-imports` | contracts in `pyproject.toml` |
| internal latency (< 200 ms) | latency | `tests/alerting/test_latency.py` | `MemoryBus` + `FakeNotifier` |

**Never** call real Telegram, WhatsApp, or the network in tests. Real SQLite (temp file or `:memory:`) is fine in adapter and web tests.

## Fakes (`tests/fakes/`)
- `InMemory<Name>Repository`: implements the same `Protocol` and **passes the same contract suite** as the SQLite one.
- `FakeNotifier`: records calls; can be told to fail N times.
- `FakeClock`: settable `now`, `advance(seconds)`.
- `MemoryBus` is the real `shared/adapters/bus_memory.py`, not a fake.

If you add a port, add its fake **and** its contract suite in the same task. Exempt: `TelegramGateway` and `Notifier` (fake only), and the read-query ports `IngestionQueries`/`AlertQueries` (SQLite-only, tested on a temp DB).

## Writing good cases
- Domain tables use real Brazilian deal-post shapes: `R$ 349`, `R$349,90`, `R$ 1.299,00`, `de R$ 499 por R$ 349`, `10x de R$ 35`, `por 589!!`, emoji, ALL CAPS, accents.
- One behavior per test; name it as the behavior: `test_installment_value_is_not_the_price`.
- Time-based rules (30-min window, expiry) use `FakeClock`. Never `sleep`.
- Async tests: `pytest-asyncio` (asyncio mode configured in `pyproject.toml`).

## Checks: all must pass before a task is done
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run lint-imports
uv run pytest -q
uv run ty check || true     # informational only, never blocks
```
Paste the real output summary in your report. "Should pass" is not evidence (`superpowers:verification-before-completion`).
