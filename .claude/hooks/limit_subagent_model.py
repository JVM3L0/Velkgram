#!/usr/bin/env python3
"""PreToolUse hook for the Agent tool: caps every subagent at Sonnet.

Haiku and Sonnet pass through. A missing model, Opus, Fable or `inherit` is
rewritten to `sonnet`, which also overrides plugin agents that pin `opus` or
`inherit` in their frontmatter. Forks are denied because they always run on
the parent's model.
"""

import json
import sys

ALLOWED_PREFIXES = ("sonnet", "haiku", "claude-sonnet", "claude-haiku")


def main() -> None:
    payload = json.load(sys.stdin)
    tool_input = dict(payload.get("tool_input") or {})

    if tool_input.get("subagent_type") == "fork":
        decision = {
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Forks run on the parent model, above the Sonnet cap for this project. "
                "Use a general-purpose (or specific) subagent with model 'sonnet' or 'haiku'."
            ),
        }
    else:
        model = str(tool_input.get("model") or "").lower()
        if model.startswith(ALLOWED_PREFIXES):
            return
        tool_input["model"] = "sonnet"
        decision = {
            "permissionDecision": "allow",
            "permissionDecisionReason": "Subagent model capped at Sonnet for this project.",
            "updatedInput": tool_input,
        }

    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}}))


if __name__ == "__main__":
    main()
