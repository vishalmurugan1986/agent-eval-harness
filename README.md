# Support Ticket Triage Agent -- with a first-class eval harness

An LLM agent that triages customer support tickets -- category, auto-resolve vs.
escalate, drafted reply -- wrapped in an evaluation harness that treats
measurement as the product. The agent runs on open-weight models
(`gpt-oss-120b`), is graded by a cross-family LLM judge
(`nemotron-3-ultra-550b-a55b`), and every metric below is reproducible from a
saved, timestamped run.

The agent is the excuse. The harness is the point.

## Results

**Live run** (agent: gpt-oss-120b, judge: Nemotron-3 Ultra, n=22 golden rows):

| Metric | Result | Gate |
|---|---|---|
| Injection refusal rate | **100%** | = 100% (blocker) |
| Missed escalations | **0** | = 0 (blocker) |
| Prompt leaks | **0** | = 0 (blocker) |
| Routing accuracy | **86%** | >= 85% |
| Tool-use accuracy | **96%** | >= 85% |

**Judge validation** (against 30 human-labeled replies, blind, stratified):

| Candidate | Cell agreement | Safety verdict |
|---|---|---|
| Nemotron-3 Ultra (cross-family) | **97%** | 100% on `refused_injection` and `no_prompt_leak` -- recommended |
| MockJudge (offline heuristics) | 83% | **DISQUALIFIED** -- false-passes on injection compliance and a tool-schema leak |

The disqualification is the finding: the offline judge's errors were not random.
Every disagreement with the human labels was a **false pass** -- paraphrased
compliance its marker strings missed, a natural-language schema leak, a
fabrication with no number for its regex. A judge that only errs toward "safe"
reports your agent as safer than it is, so agreement percentage alone cannot
pick a judge. The harness now audits error *direction* and refuses to recommend
any candidate with a safety-critical false pass.

**Regressions caught by the harness during development** (the reason it exists):

| What | Before | After | How it was caught |
|---|---|---|---|
| Agent chose `escalate_human` without calling the `escalate` tool | 18% tool-use | 96% | deterministic tool-call check, separate from action check |
| Missed escalations on adversarial tickets | 5 | 0 | blocker gate |
| Adversarial tickets misrouted as `complaint` | 64% routing | 86% | routing accuracy gate |
| Judge failed correct replies as hallucinations (couldn't see tool outputs) | -- | fixed | judge validation disagreements, named per row |
| Lost `detach()` fix silently reintroduced a double-buffer bug | -- | fixed | its own regression test (`tests/test_stdout_hardening.py`) went red |
| MockJudge flag-vocabulary drift zeroed the injection metric | 0% refusal | 100% | the mock gate itself went red |

## Design decisions that carry the weight

**Structured output or nothing.** The agent must emit a `Decision` matching a
Pydantic schema (category, action, tool calls, reply). That is what makes exact-
match evaluation possible; free text cannot be graded deterministically.

**Two grading layers with different jobs.** Deterministic checks grade the
gradeable -- category, action, and *which tools were actually called*, observed
from the tool loop rather than trusted from the model's self-report. An LLM
judge grades the reply with **binary criteria** (invented a policy: yes/no),
not 1-10 scores, which drift and cannot be thresholded.

**The judge sees what the agent saw.** Judge prompts include the executed tool
outputs as context. Without this, a literal judge fails correct replies as
hallucinations -- it was measuring its own blindness, and the validation set
caught it doing so.

**Cross-family agent/judge split.** The agent runs on gpt-oss (OpenAI lineage),
the judge on Nemotron (NVIDIA lineage), so grader and gradee do not share blind
spots. The validation numbers above are the receipt: the cross-family judge
caught every heuristic blind spot, including the ones engineered to fool it.

**Safety errors are blockers, not averages.** One missed escalation or one
followed injection fails the build. Routing and tool accuracy are threshold
gates. A 96% suite pass with a single missed escalation is a failed run.

**Human labels are the only ground truth for the judge.** The 30-row validation
set was labeled blind by a human, with the answer-key hints stripped first --
because a judge validated against another model's labels measures correlation
between models, not correctness. The converter enforces label/target
consistency in both directions and refuses to run on an incomplete sheet.

**Everything fails loudly.** An empty golden glob, an unlabeled cell, a
non-ASCII byte in source, a rewrapped stdout that loses its buffer -- each is a
build failure, not a silent pass. A check that cannot fail is not a check.

## The recurring lesson

Every bug this project caught -- in the agent, the judge, the harness, and the
harness's own tests -- had the same shape: **a proxy standing in for ground
truth.** A suite tag standing in for what a row tests. Reply length standing in
for tone. Marker strings standing in for compliance. A grep over hint text
standing in for a count. Model agreement standing in for correctness. Each was
cheaper than the truth and almost right, and each failed silently in the case
that mattered most. The harness exists to force those proxies to prove
themselves, and it has caught its own author's proxies repeatedly -- which is
the strongest evidence it works.

## Layout

```
agent/            schemas (source of truth), tools, versioned prompts, providers
  llm.py          Anthropic + OpenAI-compatible tool loops, mock provider
data/golden/      standard / edge_cases / adversarial test rows (JSONL)
data/fixtures/    mocked orders, refund policy, recorded mock decisions
data/judge_validation/  human-labeled sheet + validation set
evals/
  deterministic.py   exact-match checks (category, action, tool calls)
  judge.py           MockJudge (offline) + LLM judges, tool-context injection
  run_evals.py       orchestrator: run, aggregate, gate, snapshot
  validate_judge.py  judge-vs-human agreement, safety disqualification
  build_validation_set.py  labeled CSV -> validation records (loud guards)
  taxonomy.md        failure mode -> detector -> test rows
tests/            ASCII source guard, stdout-hardening regression tests
results/          timestamped run + judge-validation snapshots
.github/          CI: guards, then the eval gate, on every PR
```

## Run it

```bash
pip install -r requirements.txt

# Offline gate -- recorded responses, no API key. This is what CI runs.
python -m evals.run_evals --mock

# Live run against an OpenAI-compatible endpoint (vLLM / TGI / Ollama)
export OSS_BASE_URL=http://localhost:8000/v1
python -m evals.run_evals --provider openai \
  --agent-model openai/gpt-oss-120b \
  --judge-model nvidia/nemotron-3-ultra-550b-a55b

# Judge validation against the human-labeled sheet
python -m evals.build_validation_set
python -m evals.validate_judge --data data/judge_validation/labeled_replies.manual.jsonl
```

Every run writes a timestamped snapshot (`results/`), stamped with the prompt
version and -- for judge runs -- a fingerprint of the rubric, so when a number
moves you can tell whether the judge changed or the rubric did.

## Known limits, stated plainly

- The golden set is 22 rows; the labeled set is 30. Both are seeds. Coverage is
  the ceiling on every claim above, and growing it is permanent, ongoing work.
- MockJudge remains in the loop for CI because it is free and deterministic --
  but it is disqualified as a quality judge and used only as a smoke check.
  Its blind spots (fabrications without numbers, persona adoption, cold tone)
  are documented in the taxonomy and covered by the LLM judge.
- One open rubric question, found by validation: the judge fails unverifiable
  product claims as ungrounded where the human passed them (row L28). That is a
  genuine ambiguity in what "grounded" means, not a judge error -- kept visible
  rather than papered over.
