"""CLI entrypoint for running a single ticket triage."""

from __future__ import annotations

import argparse
import json

from .llm import MockProvider, OpenAICompatProvider
from .schemas import Ticket


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="mock", choices=["mock", "openai"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--id", default="t-cli")
    ap.add_argument("--customer-id", default=None)
    ap.add_argument("--order-id", default=None)
    ap.add_argument("--message", default="Where is my order? It's been two weeks.")
    args = ap.parse_args()

    ticket = Ticket(
        id=args.id,
        customer_message=args.message,
        customer_id=args.customer_id,
        order_id=args.order_id,
    )

    if args.provider == "mock":
        p = MockProvider()
    else:
        p = OpenAICompatProvider(model=args.model) if args.model else OpenAICompatProvider()

    decision = p.decide(ticket)
    print(json.dumps(decision.model_dump(), indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
