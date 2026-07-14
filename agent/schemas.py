"""Data contracts for the triage agent.

Everything downstream -- the agent, the golden data, and the eval harness --
depends on these types. If you change a category or field name, change it here
and the evals will tell you what broke.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# The closed set of categories the agent may assign. Keeping this a Literal
# means a typo'd or hallucinated category fails validation instead of silently
# passing through your metrics.
Category = Literal[
    "order_status",
    "refund_request",
    "shipping_issue",
    "product_question",
    "complaint",
    "other",
]

# Two-valued on purpose. "escalate_human" is the safety-critical branch: the
# adversarial eval set exists mostly to make sure we never miss one of these.
Action = Literal["auto_resolve", "escalate_human"]

# Tools the agent is allowed to invoke. Names must match the callables in
# tools.py exactly -- deterministic evals assert on these strings.
ToolName = Literal["order_lookup", "refund_policy", "escalate"]


class Ticket(BaseModel):
    """A single inbound support ticket -- the unit of input."""

    id: str
    customer_message: str
    customer_id: str | None = None
    order_id: str | None = None


class ToolCall(BaseModel):
    """One tool invocation the agent actually made during a run."""

    name: ToolName
    args: dict = Field(default_factory=dict)


class Decision(BaseModel):
    """The agent's structured output -- the unit the harness scores.

    Forcing the agent to emit this exact shape is what makes deterministic
    evaluation possible at all. Free-form text can't be graded by exact match.
    """

    category: Category
    action: Action
    tool_calls: list[ToolCall] = Field(default_factory=list)
    draft_reply: str
    reasoning: str = ""

    def tool_names(self) -> list[str]:
        return [tc.name for tc in self.tool_calls]
