---
name: velkgram-architecture
description: Use before creating, moving, or importing any Python module in Velkgram — where code goes (modules, domain/ports/services/adapters, apps), cross-module rules (events, public APIs, table ownership), and how to add a new adapter or module without breaking the boundaries.
---

# Velkgram architecture

Velkgram is a **modular monolith with hexagonal modules** (spec: `docs/superpowers/specs/2026-11-04-velkgram-design.md`, §4). If the spec and this skill disagree, the spec wins. Report the conflict; don't pick one silently.

## Layout

```
velkgram/
  shared/        events.py (plain-data payloads), ports.py (EventBus, Clock, ChangeSignal),
                 adapters/ (bus_memory, signal_polling, clock_system), config.py, db.py
  channels/  wishlist/  ingestion/  alerting/  reporting/     ← business modules
    __init__.py   public API: the only thing other modules may import
    domain/       pure Python: dataclasses + rules. No I/O, no third-party libs.
    ports/        typing.Protocol contracts the services need
    services/     use cases; depend on own domain + ports + shared only
    adapters/     sqlite/, telethon/, notify_*.py … implement ports
    web/          FastAPI router + Jinja templates for this module's pages
    migrations/   NNN_description.sql, owned by this module
  apps/          composition roots: collector/main.py, web/main.py, cli.py
```

## Where does my code go?

| You are writing… | Put it in |
|---|---|
| A rule that needs no I/O (matching, price parsing, dedup key) | `<module>/domain/` |
| "Something the service needs from outside" | a `Protocol` in `<module>/ports/` |
| A use case wiring domain + ports | `<module>/services/` |
| SQL, Telethon, HTTP, filesystem | `<module>/adapters/<tech>/` |
| An event another module reacts to | a frozen dataclass in `shared/events.py` |
| Choosing which adapter to use | `apps/*` only |
| A page | `<module>/web/` of the module that **owns the data** |

## Hard rules (enforced by `import-linter`, CI fails otherwise)

1. `*/domain` imports only stdlib + `shared.events` + `shared.text`.
2. `*/services` imports only its own `domain`, `ports`, and `shared`.
3. **No module imports another module's internals.** Cross-module: events, or a port in the consumer whose adapter calls the producer's `__init__` public API.
4. **Only `apps/*` imports `*/adapters`.**
5. **Each module owns its tables.** Never `SELECT` from another module's table. Add a query function to the owner's public API instead.
6. **Event payloads are plain data** (ids, str, int, datetime, tuples). Never put a module's domain type in an event.

## Recipes

**New adapter for an existing port** (e.g. `bus_redis`, Postgres repo):
1. Implement the `Protocol` in `<module>/adapters/<tech>/`.
2. Run the port's **contract test suite** against it (`tests/contracts/`). It must pass unchanged.
3. Wire it in `apps/*` behind an env setting. Don't touch `domain` or `services`.

**Cross-module read** (e.g. `alerting` needs wishes):
1. Define the port in the consumer: `alerting/ports/wishlist_reader.py`.
2. The producer's `__init__.py` exports what's needed (e.g. `wishlist.WishRepository`, `wishlist.Wish`).
3. The adapter lives in the consumer (`alerting/adapters/wishlist_api.py`), receives the producer's port instance (built by `apps`), and converts to the consumer's own view type.

**New module:** create the folder skeleton above, add its `forbidden` boundary contract to `[tool.importlinter]` in `pyproject.toml` (and add it to the other modules' forbidden lists), and add its migrations folder to `velkgram migrate`.

**Cross-module read query** (reporting, web pages): define a query `Protocol` in the owner's `ports/queries.py`, export it from the owner's `__init__`, implement it in the owner's `adapters/sqlite/queries.py`, and let `apps` construct it and inject it. Public APIs never export adapter factories.

## Red flags. Stop and rethink.
- `from velkgram.ingestion.domain import ...` inside `alerting/` → rule 3.
- `import sqlite3` / `telethon` / `fastapi` in `domain/` or `services/` → rules 1–2.
- A service that builds its own adapter (`SqliteRepo(...)`) → it must receive the port by constructor.
- A SQL `JOIN` across two modules' tables → rule 5.
- Network calls on the alert critical path (link resolution, LLM) → spec §6.2 forbids it.
