# Standardized Agentic Tool Evaluation and Skill Pipeline Specification

## 1. Overview
This document defines the standardized execution lifecycle for agent tool calling, Just-In-Time (JIT) skill resolution, observation evaluation, and autonomous skill synthesis across ARES and connected agent runtimes.

---

## 2. The 5-Stage Agent Execution Pipeline

Every agent turn adheres to the following sequential lifecycle:

```
┌──────────────────────────┐
│ 1. Intent & Capability   │ ──> Evaluates user prompt against skill descriptions and available tools
└────────────┬─────────────┘
             │
             ▼
     [Skill Exists?]
       ├── YES ──> [Load SKILL.md & Dynamic Tool Bindings] ──┐
       └── NO  ──> [Research & Structured Planning Phase]  ──┤
                                                             │
                                                             ▼
┌──────────────────────────┐                  ┌──────────────────────────┐
│ 3. Guarded Execution     │ <─────────────── │ 2. Plan / Playbook Setup │
│ (Call ➔ Observe ➔ Eval)  │                  └──────────────────────────┘
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ 4. Verification Gate     │ ──> Confirms real-world state changed as requested
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ 5. Skill Synthesis       │ ──> If novel workflow, compile & persist new SKILL.md
└──────────────────────────┘
```

### Stage 1: Intent & Capability Evaluation
- The agent analyzes incoming prompt intent and checks registered skills in `.gemini/config/skills/` and workspace customization roots.
- **Match Found:** The agent invokes `view_file` on `SKILL.md` to load the exact procedures and helper tools Just-In-Time (JIT).

### Stage 2: Skill-Gap Fallback (Research & Plan)
- If no matching skill exists for a non-trivial domain, the agent is **strictly prohibited from blind tool spamming or raw scripting guessing**.
- The agent must:
  1. **Research & Probe:** Inspect environmental APIs, documentation, or schemas.
  2. **Draft Plan:** Produce a step-by-step plan before performing batch actions.

### Stage 3: Guarded Execution & Tool Evaluation Contract
Every tool invocation follows the **Call → Observe → Evaluate → Decide** loop. Before triggering the next tool:
1. **Status Check:** Did the tool exit with code `0`?
2. **Payload Validation:** Did it return actual data, or is it empty/null?
3. **Error Categorization:** Classify failures immediately (*Permission Denied*, *Syntax Error*, *Path Not Found*, *Execution Timeout*).
4. **Repetition Circuit Breaker (3-Strike Rule):**
   - 2 consecutive identical failures/empty outputs ➔ Halt immediately.
   - 3 consecutive syntax variations of a failed command ➔ Halt and ask user for clarification.

### Stage 4: Verification Gate
- Real-world validation to verify that the task achieved its goal (e.g. email moved, file written, test suite green).

### Stage 5: Autonomous Skill Synthesis (Self-Improvement)
- When a novel, complex task succeeds without a prior skill, the agent synthesizes the successful workflow into a new `SKILL.md` (and optional scripts) under `.gemini/config/skills/<skill_name>/`.
- Future executions execute deterministically with zero trial-and-error overhead.

---

## 3. Timeouts & Task-Aware Budgeting

- **Interactive System & Query Tasks:** Default 5–15s timeout.
- **Heavy Tasks (Builds, Compilations, Model Syncs, Large Downloads):** Configurable generous timeouts (60–300s).
- **Timeout Feedback:** Any command that hits a timeout emits a structured observation (`status: TIMEOUT, elapsed: Xs`) rather than locking the turn. The agent must narrow its scope or batch size rather than repeating the identical command.
