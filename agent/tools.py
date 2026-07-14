"""Mocked implementations of the agent's tools.

Every tool reads from local fixtures instead of a real API. That buys you three
things the eval harness needs: determinism (same input, same output every run),
zero cost, and clean attribution -- when a test fails, it's the agent's fault,
not a flaky network call.

When you're ready to go real, swap the bodies here for actual API clients and
keep the signatures identical; nothing else in the repo has to change.
"""

from __future__ import annotations

import json
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"


def _load_orders() -> dict:
    with open(_FIXTURES / "orders.json", encoding="utf-8") as f:
        return json.load(f)


def order_lookup(order_id: str) -> dict:
    """Return the order record for an id, or a not-found marker."""
    orders = _load_orders()
    if order_id in orders:
        return {"found": True, **orders[order_id]}
    return {"found": False, "order_id": order_id}


def refund_policy() -> dict:
    """Return the canonical refund policy text.

    The agent should ground refund answers in THIS string. If a reply cites a
    policy detail that isn't here, that's a hallucination the judge should catch.
    """
    with open(_FIXTURES / "refund_policy.md", encoding="utf-8") as f:
        return {"policy": f.read().strip()}


def escalate(reason: str) -> dict:
    """Hand the ticket to a human. Recording this call is the whole point of the
    safety-critical 'missed escalation' metric."""
    return {"escalated": True, "reason": reason}


# Registry the agent loop uses to dispatch tool calls by name.
TOOLS = {
    "order_lookup": order_lookup,
    "refund_policy": refund_policy,
    "escalate": escalate,
}

# Canonical tool specs (single source of truth). Converted to the OpenAI
# function-calling shape by to_openai_tools(); prompt and API stay in sync.
TOOL_SPECS = [
    {
        "name": "order_lookup",
        "description": "Look up an order by its id. Use when the customer references an order or asks about status, shipping, or a specific purchase.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "refund_policy",
        "description": "Fetch the current refund policy text. Call this before making any claim about refund eligibility, windows, or amounts.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "escalate",
        "description": "Escalate the ticket to a human agent. Use for anything you cannot resolve confidently, or anything involving money movement, legal threats, or safety.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]


def to_openai_tools() -> list[dict]:
    """Same tools, reshaped for OpenAI-compatible chat-completions endpoints."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOL_SPECS
    ]
