# Velkgram

Personal app: real-time wishlist alerts from Telegram deal channels (Python, Telethon, FastAPI, SQLite).

- **Spec (source of truth):** `docs/superpowers/specs/2026-11-04-velkgram-design.md`
- **Plans / backlog:** `docs/superpowers/plans/`

## Project skills (load before working)
- `velkgram-architecture`: where code goes, module boundaries
- `velkgram-conventions`: naming, types, errors, logging, secrets, commits
- `velkgram-testing`: TDD, test layers, fakes, required checks
- `velkgram-task`: how a subagent executes one backlog task and reports

## Rules
- All repo artifacts in English; user-facing text (alerts, web UI) in Portuguese.
- Subagents run on Sonnet or Haiku only. `.claude/hooks/limit_subagent_model.py` enforces it and denies forks.
- Never commit secrets, `.env`, `*.session`, or database files. Never push without being asked.

## Checks
```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest -q
```
