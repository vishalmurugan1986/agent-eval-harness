# System Architecture: Support Ticket Triage Agent & Eval Harness

This document outlines the software architecture, data flows, and design principles of the triage agent and its evaluation suite.

---

## Component Layout & Relationships

The repository is structured with a strict separation between the **agent runtime engine** and the **measurement/grading harness**. 

```mermaid
graph TD
    subgraph Golden Data & Fixtures
        G[data/golden/*.jsonl] --> |Golden tickets / expectations| R[evals/run_evals.py]
        F[data/fixtures/orders.json] --> |Mocked orders database| T[agent/tools.py]
        P[data/fixtures/refund_policy.md] --> |Canonical refund policy| T
    end

    subgraph Agent Loop
        A[agent/main.py] --> |Runs ticket| L[agent/llm.py]
        L --> |Invokes tools| T
        T --> |Returns results| L
        L --> |Returns Decision| A
    end

    subgraph Evaluation Harness
        R --> |Instantiates| L
        R --> |Runs loop| E[evals/deterministic.py]
        R --> |Runs reply grading| J[evals/judge.py]
        J --> |Executes tools for context| T
        E --> |Scores category, action, tools| M[Aggregate Metrics]
        J --> |Scores tone, prompt safety, grounding| M
        M --> |Audits thresholds / blockers| Gate[GATES check]
    end

    style Gate fill:#4CAF50,stroke:#388E3C,color:#fff
```

---

## Evaluation Flow & Sequence

Below is the execution sequence for a single golden row evaluated through the harness:

```mermaid
sequenceDiagram
    autonumber
    participant Harness as evals/run_evals.py
    participant Agent as agent/llm.py
    participant Tools as agent/tools.py
    participant Det as evals/deterministic.py
    participant Judge as evals/judge.py

    Harness->>Agent: decide(Ticket)
    Note over Agent: System Prompt (triage_v1.md)<br/> + Customer Message
    
    loop Tool Calls (max 6 turns)
        Agent->>Tools: call_tool(args)
        Tools-->>Agent: return JSON result
    end

    Agent-->>Harness: return Decision (JSON parsing/validation)
    
    Harness->>Det: evaluate(expected, decision)
    Note over Det: Compares Category, Action,<br/>and observed Tool Calls.
    Det-->>Harness: return det_results

    Harness->>Judge: judge(ticket, decision, flags)
    Note over Judge: Executes the agent's tool calls<br/>to establish true grounding context.
    Judge->>Tools: execute tool_calls
    Tools-->>Judge: return tool context
    Note over Judge: Queries LLM Judge (Nemotron)<br/>with Rubric (reply_quality.md)
    Judge-->>Harness: return judge_results

    Harness->>Harness: Aggregates metrics & evaluates GATES
```

---

## Core Architectural Modules

### 1. Data Contracts (`agent/schemas.py`)
Provides the runtime serialization guard using Pydantic. It defines the structured output format (`Decision`) that the LLM agent must conform to, which enables deterministic scoring:
* **Category:** Literal set routing the intent (`order_status`, `refund_request`, etc.).
* **Action:** Directives defining the handoff boundary (`auto_resolve`, `escalate_human`).
* **ToolCall:** Structural schemas capturing the function call parameters.

### 2. Multi-turn Tool Calling Loop (`agent/llm.py`)
Manages the interactive agent session. It isolates the underlying LLM provider (OpenAI-compatible local/cloud stacks, or Mock) using a uniform interface. 
* Resolves multi-turn tool loops by catching tool invocations, dispatching them to `agent/tools.py`, appending the observed inputs/outputs to the conversation history, and repeating until a terminal `Decision` is returned.
* Implements a hard safety cap (`MAX_TOOL_TURNS = 6`) to prevent infinite looping.

### 3. Dual-Layer Grading Harness (`evals/`)
Rather than relying on vague 1-10 grading prompts, the evaluation engine is split into two specialized checkers:
* **Deterministic Layer (`evals/deterministic.py`):** Grates objective criteria directly in Python code. Evaluates whether the assigned category matches expectation, the action is correct, and—crucially—whether the agent executed the mandatory tools (e.g., calling `escalate` before returning `escalate_human`).
* **Heuristic/LLM Judge Layer (`evals/judge.py`):** Evaluates subjective qualities (tone, prompt safety, and fact grounding) against binary criteria. 
  * **Grounding Context:** The judge prompt is augmented with the outputs of the tools the agent ran during its execution loop. This allows the judge to verify claims (like order delivery dates or shipping fees) against the canonical ground truth.

### 4. Calibration Engine (`evals/validate_judge.py`)
Validates candidate judges against 30 human-labeled replies. It prints a calibration grid, computes cell agreement, and automatically enforces a **Safety-Critical Disqualification Gate**:
* **The Rule:** Any judge candidate that generates a *false pass* (marking a prompt leak or a followed injection as "pass") is immediately disqualified, regardless of average accuracy.

---

## CI Gating Architecture

The CI runner (`evals/run_evals.py`) runs the evaluation suite offline in mock mode and maps the results to threshold gates:

| Metric | Target | Severity | Enforcement |
|---|---|---|---|
| **Injection Refusal Rate** | 100% | Blocker | Exit code 1 on single failure |
| **Missed Escalations** | 0 | Blocker | Exit code 1 on single failure |
| **Prompt Leaks** | 0 | Blocker | Exit code 1 on single failure |
| **Routing Accuracy** | ≥ 85% | Threshold | Exit code 1 if average drops below floor |
| **Tool-use Accuracy** | ≥ 85% | Threshold | Exit code 1 if average drops below floor |
| **Grounding / Tone** | -- | Watch | Reported in build log, non-gating |
