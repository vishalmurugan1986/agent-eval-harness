"""Deterministic evals: the cheap, unambiguous half of the harness.

These are exact-match assertions on the structured parts of the Decision --
category, action, and which tools were called. No model judgment, no flakiness.
If one of these fails, it's a real regression, full stop. The two named
failure modes below (missed / unnecessary escalation) are broken out separately
because they matter far more than raw accuracy: a missed escalation is the one
error that can actually hurt a customer.
"""

from __future__ import annotations

from agent.schemas import Decision


def evaluate(expected: dict, decision: Decision) -> dict:
    called = set(decision.tool_names())
    must_call = set(expected.get("must_call", []))
    must_not_call = set(expected.get("must_not_call", []))

    category_match = decision.category == expected["category"]
    action_match = decision.action == expected["action"]

    exp_action = expected["action"]
    missed_escalation = exp_action == "escalate_human" and decision.action != "escalate_human"
    unnecessary_escalation = exp_action == "auto_resolve" and decision.action == "escalate_human"

    missing_tools = must_call - called
    forbidden_tools = must_not_call & called
    tool_ok = not missing_tools and not forbidden_tools

    return {
        "category_match": category_match,
        "action_match": action_match,
        "missed_escalation": missed_escalation,
        "unnecessary_escalation": unnecessary_escalation,
        "tool_ok": tool_ok,
        "missing_tools": sorted(missing_tools),
        "forbidden_tools": sorted(forbidden_tools),
        # A row "passes" deterministic evals only if everything lines up.
        "passed": category_match and action_match and tool_ok,
    }
