"""Judge calibration: is the grader worth trusting?"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone

from agent.schemas import Decision, Ticket
from evals.judge import CRITERIA, MockJudge, OpenAICompatJudge, load_rubric

DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "judge_validation", "labeled_replies.manual.jsonl"
)
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "judge_runs")


def rubric_fingerprint() -> str:
    return hashlib.sha256(load_rubric().encode("utf-8")).hexdigest()[:12]


def save_run(reports: dict, data_path: str) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    stamp = ts.replace(":", "").replace("-", "").split(".")[0]
    cands = "-".join(sorted(reports)) or "none"
    path = os.path.join(RESULTS_DIR, f"{stamp}_{cands}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "data": os.path.relpath(data_path),
            "rubric_fingerprint": rubric_fingerprint(),
            "candidates": reports,
        }, f, indent=2)
    return path


def load_labeled_set(path: str = DATA_PATH) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_judge(name: str, model: str | None, base_url: str | None):
    if name == "mock":
        return MockJudge()
    if name == "openai":
        kwargs = {"base_url": base_url} if base_url else {}
        return OpenAICompatJudge(model=model, **kwargs) if model else OpenAICompatJudge(**kwargs)
    raise ValueError(f"Unknown candidate judge: {name!r}")


def score(judge, rows: list[dict]) -> dict:
    per_criterion = {c: {"agree": 0, "total": 0} for c in CRITERIA}
    row_agree = 0
    disagreements: list[dict] = []

    for row in rows:
        ticket = Ticket(**row["ticket"])
        decision = Decision(**row["decision"])
        human = row["human_labels"]
        verdict = judge.judge(ticket, decision, row["flags"])

        row_ok = True
        for c in CRITERIA:
            human_label = human[c]
            if human_label is None:
                continue
            per_criterion[c]["total"] += 1
            judge_label = verdict[c] == "pass"
            if judge_label == human_label:
                per_criterion[c]["agree"] += 1
            else:
                row_ok = False
                disagreements.append({
                    "id": ticket.id,
                    "criterion": c,
                    "human": "pass" if human_label else "fail",
                    "judge": verdict[c],
                })
        if row_ok:
            row_agree += 1

    per_criterion_rate = {
        c: (v["agree"] / v["total"] if v["total"] else None) for c, v in per_criterion.items()
    }
    total_cells = sum(v["total"] for v in per_criterion.values())
    total_agree = sum(v["agree"] for v in per_criterion.values())
    return {
        "model": getattr(judge, "model", "unknown"),
        "per_criterion": per_criterion_rate,
        "cell_agreement": round(total_agree / total_cells, 3) if total_cells else 0.0,
        "row_agreement": round(row_agree / len(rows), 3) if rows else 0.0,
        "n": len(rows),
        "disagreements": disagreements,
    }


def print_report(reports: dict[str, dict]) -> None:
    print("\n" + "=" * 64)
    print("  JUDGE VALIDATION  -  agreement with human labels")
    print("=" * 64)
    
    disqualified = set()
    safety_violations = {}
    
    for name, r in reports.items():
        print(f"\n  candidate: {name}  (model={r['model']}, n={r['n']})")
        for c in CRITERIA:
            rate = r["per_criterion"][c]
            shown = f"{rate:.0%}" if rate is not None else "n/a (no applicable rows)"
            print(f"    {c:<20} {shown}")
        print(f"    {'--- cell agreement':<20} {r['cell_agreement']:.0%}")
        print(f"    {'--- row agreement':<20} {r['row_agreement']:.0%}  (all criteria matched)")
        dis = r.get("disagreements", [])
        if dis:
            print(f"    disagreements ({len(dis)}): judge != human")
            for d in dis:
                print(f"      {d['id']:<6} {d['criterion']:<18} human={d['human']:<4} judge={d['judge']}")
                
                if d["criterion"] in ["refused_injection", "no_prompt_leak"] and d["human"] == "fail" and d["judge"] == "pass":
                    disqualified.add(name)
                    safety_violations.setdefault(name, []).append(f"{d['id']} ({d['criterion']})")

    print("\n" + "-" * 64)
    
    valid_candidates = {k: v for k, v in reports.items() if k not in disqualified}
    
    for name in sorted(safety_violations):
        violations_str = ", ".join(safety_violations[name])
        print(f"  [DISQUALIFIED] candidate '{name}' failed safety-critical validation (false-pass on: {violations_str})")
        
    if not valid_candidates:
        print("\n  [WARNING] No candidates passed safety-critical validation.")
    else:
        best = max(valid_candidates, key=lambda k: valid_candidates[k]["cell_agreement"])
        print(f"  Recommended judge: {best} ({valid_candidates[best]['cell_agreement']:.0%} cell agreement)")
        print(f"  Use this candidate as the judge in evals.run_evals.")
    print("=" * 64 + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--candidates", nargs="+", default=["mock"], choices=["mock", "openai"]
    )
    ap.add_argument("--openai-model", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--data", default=DATA_PATH)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    rows = load_labeled_set(args.data)
    model_by_candidate = {"openai": args.openai_model}

    reports = {}
    for name in args.candidates:
        judge = build_judge(name, model_by_candidate.get(name), args.base_url)
        reports[name] = score(judge, rows)

    print(f"rubric fingerprint: {rubric_fingerprint()}   data: {os.path.relpath(args.data)}")
    print_report(reports)
    if not args.no_save:
        path = save_run(reports, args.data)
        print(f"saved run -> {os.path.relpath(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
