"""Convert a filled labeling sheet into the set validate_judge.py consumes."""

from __future__ import annotations

import argparse
import csv
import json
import re
import os

from agent.schemas import Decision, Ticket
from evals.judge import CRITERIA

_HERE = os.path.dirname(__file__)
DEFAULT_IN = os.path.join(_HERE, "..", "data", "judge_validation", "labeling_sheet.csv")
DEFAULT_OUT = os.path.join(_HERE, "..", "data", "judge_validation", "labeled_replies.manual.jsonl")

_LABEL_MAP = {"pass": True, "fail": False, "na": None}


def _parse_label(raw: str) -> tuple[bool | None, str | None]:
    v = (raw or "").strip().lower()
    if v == "":
        return None, "blank"
    if v not in _LABEL_MAP:
        return None, f"not pass/fail/na: {raw!r}"
    return _LABEL_MAP[v], None


def _load_targets(path: str) -> dict[str, list[str]]:
    m: dict[str, list[str]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                m[rec["id"]] = rec.get("targets", [])
    return m


def convert(in_path: str, out_path: str, targets_path: str) -> int:
    with open(in_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"No rows in {os.path.abspath(in_path)} -- nothing to convert.")
    targets_map = _load_targets(targets_path)

    problems: list[str] = []
    inconsistencies: list[str] = []
    out_lines: list[str] = []

    for row in rows:
        rid = row.get("id", "?")
        suite = row.get("suite", "")
        labels: dict[str, bool | None] = {}
        for c in CRITERIA:
            value, err = _parse_label(row.get(c, ""))
            if err:
                problems.append(f"{rid}.{c}: {err}")
            labels[c] = value

        if rid not in targets_map:
            problems.append(f"{rid}: no matching row in targets file {os.path.basename(targets_path)}")
        targets = targets_map.get(rid, [])

        applies_ri = "refused_injection" in targets
        flags = ["injection"] if applies_ri else []

        human_ri = labels.get("refused_injection")
        if applies_ri and human_ri is None:
            inconsistencies.append(
                f"{rid}: targets include refused_injection but it's labeled na -> mark it pass/fail"
            )
        if not applies_ri and human_ri is not None:
            inconsistencies.append(
                f"{rid}: refused_injection labeled but targets say no injection here -> mark it na"
            )

        tool_calls = []
        msg = row.get("ticket", "")
        # Check for order lookup
        order_match = re.search(r"A\d+", msg)
        if order_match:
            tool_calls.append({
                "name": "order_lookup",
                "args": {"order_id": order_match.group(0)}
            })
        # Check for refund policy
        if any(w in msg.lower() for w in ["refund", "return", "policy", "box", "months"]):
            tool_calls.append({
                "name": "refund_policy",
                "args": {}
            })

        category = "other"
        action = "escalate_human" if suite == "adv" else "auto_resolve"
        ticket = Ticket(id=rid, customer_message=msg)
        decision = Decision(
            category=category, action=action, tool_calls=tool_calls,
            draft_reply=row.get("reply", ""), reasoning="",
        )
        out_lines.append(json.dumps({
            "id": rid,
            "suite": suite,
            "ticket": ticket.model_dump(),
            "decision": decision.model_dump(),
            "flags": flags,
            "human_labels": labels,
        }, ensure_ascii=False))

    if problems:
        raise SystemExit(
            f"{len(problems)} un-labeled or invalid cell(s) in {os.path.abspath(in_path)} -- "
            "refusing to build a validation set over an incompletely labeled sheet."
        )
    if inconsistencies:
        raise SystemExit(
            f"{len(inconsistencies)} refused_injection applicability mismatches: refusing to build."
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")
    return len(out_lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default=DEFAULT_IN)
    ap.add_argument("--out", dest="out_path", default=DEFAULT_OUT)
    ap.add_argument("--targets", default=None)
    args = ap.parse_args()
    targets_path = args.targets or os.path.join(os.path.dirname(args.in_path), "labeling_sheet.jsonl")
    n = convert(args.in_path, args.out_path, targets_path)
    print(f"wrote {n} labeled rows -> {os.path.relpath(args.out_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
