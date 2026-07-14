"""LLM providers behind a single tiny interface.

The agent doesn't care which one it's talking to -- it hands a Ticket to a
provider and gets a Decision back.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .schemas import Decision, Ticket, ToolCall
from .tools import TOOLS, TOOL_SPECS, to_openai_tools

DEFAULT_OSS_BASE_URL = os.getenv("OSS_BASE_URL", "http://localhost:8000/v1")
DEFAULT_OSS_API_KEY = os.getenv("OSS_API_KEY", "EMPTY")

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"

MAX_TOOL_TURNS = 6


def load_prompt(version: str = "triage_v1") -> str:
    # Guard against path traversal if the version string ever comes from
    # config/user input: resolve and require it to stay inside _PROMPT_DIR.
    path = (_PROMPT_DIR / f"{version}.md").resolve()
    if _PROMPT_DIR.resolve() not in path.parents:
        raise ValueError(f"prompt version escapes prompt dir: {version!r}")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _parse_decision(text: str, tool_calls: list[ToolCall]) -> Decision:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    payload = json.loads(cleaned[start : end + 1])
    payload["tool_calls"] = [tc.model_dump() for tc in tool_calls]
    return Decision(**payload)


class MockProvider:
    def __init__(self, responses_path: str | None = None, prompt_version: str = "mock"):
        path = Path(responses_path) if responses_path else _FIXTURES / "mock_responses.jsonl"
        self.prompt_version = prompt_version
        self.model = "mock"
        self._by_id: dict[str, dict] = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    self._by_id[rec["ticket_id"]] = rec["decision"]

    def decide(self, ticket: Ticket) -> Decision:
        if ticket.id not in self._by_id:
            raise KeyError(f"No mock response recorded for ticket {ticket.id!r}")
        return Decision(**self._by_id[ticket.id])


class OpenAICompatProvider:
    def __init__(
        self,
        model: str = "gpt-oss-120b",
        base_url: str | None = None,
        api_key: str | None = None,
        prompt_version: str = "triage_v1",
    ):
        import openai

        self.model = model
        self.prompt_version = prompt_version
        self.base_url = base_url or DEFAULT_OSS_BASE_URL
        self.client = openai.OpenAI(
            base_url=self.base_url,
            api_key=api_key or DEFAULT_OSS_API_KEY,
            timeout=120.0,      # a hung endpoint must not hang the suite
            max_retries=2,
        )
        self.system = load_prompt(prompt_version)
        self.tools = to_openai_tools()

    def decide(self, ticket: Ticket) -> Decision:
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": _ticket_to_text(ticket)},
        ]
        observed: list[ToolCall] = []

        for _ in range(MAX_TOOL_TURNS):
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
                temperature=0,
                max_tokens=1024,
            )
            msg = resp.choices[0].message

            if msg.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments or "{}")
                    observed.append(ToolCall(name=tc.function.name, args=args))
                    out = TOOLS[tc.function.name](**args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(out),
                        }
                    )
                continue

            return _parse_decision(msg.content or "", observed)

        raise RuntimeError("Agent exceeded MAX_TOOL_TURNS without a final decision")


def _ticket_to_text(ticket: Ticket) -> str:
    lines = [f"Ticket id: {ticket.id}"]
    if ticket.customer_id:
        lines.append(f"Customer id: {ticket.customer_id}")
    if ticket.order_id:
        lines.append(f"Referenced order id: {ticket.order_id}")
    lines.append(f"Message:\n{ticket.customer_message}")
    return "\n".join(lines)
