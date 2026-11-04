---
name: velkgram-task
description: Use when you are a subagent implementing one Velkgram backlog task from the implementation plan — how to scope the work, which skills to load, the budget rules, the definition of done, and the exact report format to return to the orchestrator.
---

# Executing one Velkgram task

You implement **exactly one task** from `docs/superpowers/plans/`. The orchestrator gave you its id.

## Before coding
1. Read the task block in the plan and **only** the spec sections it cites. Don't read the whole spec or repo.
2. Load `velkgram-architecture`, `velkgram-conventions`, `velkgram-testing`.
3. If the task is ambiguous or conflicts with the spec, **stop and report `BLOCKED`** with the question. Don't guess on architecture.

## While coding
- TDD per `velkgram-testing`. Stay inside the files the task lists. Touching others needs a one-line justification in the report.
- No scope creep: no "while I'm here" refactors, no features from §13 (future direction).
- Ask for more context instead of exploring broadly.

## Budget (usage limits matter)
- You run on **Sonnet or Haiku only**. Never spawn forks or Opus/Fable subagents. A project hook enforces this anyway.
- Don't spawn subagents unless the task says to.
- Read files in ranges, grep before reading, and don't re-read files you just edited.
- Run the narrowest test first (`uv run pytest tests/<path> -q`), the full check list once at the end.
- If you hit 3 failed attempts at the same error, stop and report `BLOCKED` with the error. Don't burn budget on loops.

## Definition of done
- [ ] Tests written first and now passing.
- [ ] All checks from `velkgram-testing` pass (ty informational).
- [ ] `import-linter` contracts pass. No new boundary exceptions.
- [ ] One commit (Conventional Commits, English, with the session's `Co-Authored-By` trailer) on the current branch. Never push.
- [ ] No secrets, `.env`, `.session`, or DB files staged.

## Report format (return exactly this)
```
STATUS: DONE | BLOCKED | PARTIAL
TASK: <id> <title>
COMMIT: <sha> <subject>        (DONE/PARTIAL)
FILES: <changed files>
CHECKS: ruff ✓ | format ✓ | pyright ✓ | lint-imports ✓ | pytest N passed | ty <n issues, informational>
NOTES: <deviations from the plan, files touched outside scope + why, follow-ups>
BLOCKER: <question or error>  (BLOCKED only)
```
