# Security Notes

## Threat model and in-code mitigations

| Threat | Mitigation | Where |
|---|---|---|
| Prompt injection via ticket text (agent) | Tickets treated as untrusted data; instruction-override, persona, encoded-payload, and pressure attacks covered by the adversarial suite; refusal is a CI blocker (100% required) | `agent/prompts/triage_v1.md`, `data/golden/adversarial.jsonl`, gate in `evals/run_evals.py` |
| Prompt injection via ticket/reply text (judge) | Ticket and reply delimited as `<untrusted_*>` blocks; judge explicitly instructed that nothing inside them can alter rubric or output format | `evals/judge.py::build_judge_prompt` |
| Side-effect replay during grading | Judge replays READ-ONLY tools only (`order_lookup`, `refund_policy`); side-effectful tools (`escalate`) are recorded but never re-executed | `evals/judge.py::build_judge_prompt` |
| Unauthorized money movement / unsafe auto-resolution | Money, legal, and safety tickets must escalate; a single missed escalation fails the build | prompt rules + `missed_escalations` blocker gate |
| Prompt/tool-schema exfiltration | Leak attempts in adversarial suite; `prompt_leaks = 0` is a blocker; judge criterion `no_prompt_leak` | golden data + gates + rubric |
| Runaway agent loops | `MAX_TOOL_TURNS = 6` hard cap | `agent/llm.py` |
| Hung LLM endpoints | 120s client timeout, 2 retries on agent and judge clients | `agent/llm.py`, `evals/judge.py` |
| Path traversal via prompt version | `load_prompt` resolves and rejects paths escaping the prompt dir | `agent/llm.py` |
| Malformed model output | All agent output validated through Pydantic `Decision`; invalid JSON/enum fails the row, never silently passes | `agent/schemas.py` |
| Encoding-based crashes (input and output) | UTF-8 pinned on all text I/O; stdout/stderr hardened with detach-safe rewrap; regression-tested | `evals/run_evals.py`, `tests/test_stdout_hardening.py` |
| Secrets in repo | No hardcoded keys; endpoint/key via `OSS_BASE_URL` / `OSS_API_KEY` env vars; `.env` gitignored | `.gitignore`, provider constructors |

## What a real deployment must add (not covered here)

- **PII handling.** Golden rows, run snapshots (`results/`), and judge prompts
  contain full ticket text. With real customer data, snapshots become PII at
  rest: encrypt, retention-limit, and access-control them, and scrub tickets
  before committing any new golden rows.
- **Authenticated tool backends.** The mocked tools read local fixtures. Real
  `order_lookup` must enforce per-customer authorization server-side -- the
  adversarial suite includes a cross-customer harvest attempt (`t-adv-4`)
  precisely because the model must not be the only line of defense.
- **Rate limiting / abuse controls** on the ticket intake path.
- **Human-in-the-loop guarantee.** `escalate` must route to a real queue with
  delivery confirmation; the agent's safety story assumes escalation works.
- **Model supply chain.** Pin exact model builds/revisions at the serving
  layer; re-run the eval gate and judge validation on every model upgrade
  (the rubric fingerprint in judge snapshots exists to make this auditable).
