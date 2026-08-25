# Unified 3-Layer Agent Architecture & Downtime Cognitive Standard

## 1. Overview & Architecture Philosophy
This specification establishes the gold-standard 3-Layer Agent Architecture for ARES & JaegerAI, eliminating overlapping mode menus by cleanly separating **Foreground Interaction**, **Specialized Task Engines**, and **Downtime Subconscious Autonomy**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: FOREGROUND PROMPT COMPOSER (Active User Focus)                     │
│ 💬 Ask (Read-Only Q&A)  |  📋 Plan (Architect First)  |  ⚡ Agent (Autonomous) │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 2: SPECIALIZED GOAL & SKILL ENGINE (JIT Intent & Slash Commands)      │
│ • /research ➔ Deep Multi-Source Synthesis                                   │
│ • /audit    ➔ Security, SAIF & Rule Verification                            │
│ • /mail     ➔ Deterministic Apple Mail Triage (macos-mail-organizer)         │
│ • Custom    ➔ Loaded Just-In-Time via SKILL.md                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 3: DOWNTIME SUBCONSCIOUS ENGINE (System Idle & Off-Hours Only)        │
│ • Downtime Wondering ➔ Explores test debts & optimizations during idle       │
│ • Downtime Dreaming  ➔ Automatic memory distillation (Episodic ➔ Semantic)  │
│ • Downtime Standby   ➔ Zero-CPU power management when inactive              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Layer-by-Layer Specification

### Layer 1: Foreground Prompt Autonomy (At the Input Bar)
Controlled directly at the composer input box (where user focus resides):
1. **`💬 Ask / Chat` (Read-Only):**
   - Answers questions, explains code, explores architecture.
   - Strictly forbidden from modifying files or running destructive shell commands.
2. **`📋 Plan` (Architect First):**
   - Deeply inspects the codebase and drafts a structured implementation plan and diff.
   - Waits for user approval before making file changes.
3. **`⚡ Agent / Auto` (End-to-End Execution):**
   - Executes multi-step tool loops with verification until task completion.

---

### Layer 2: Specialized Goal & Skill Engine (On-Demand)
Specialized capabilities are **not permanent UI modes**; they are invoked dynamically via prompt intent or slash commands:
- **/research:** Deep multi-source web and codebase investigation engine.
- **/audit:** Non-destructive compliance and vulnerability scanner.
- **/mail:** Bounded, account-aware email organizer (`macos-mail-organizer`).
- **JIT Custom Skills:** Automatically loads procedure instructions from `.gemini/config/skills/<skill_name>/SKILL.md` upon prompt match.

---

### Layer 3: Downtime Subconscious Engine (Idle / Off-Hours Only)
**Critical Contract:** Layer 3 operations execute **ONLY when the user is NOT actively working** on the system.

1. **Downtime Wondering (Proactive Companion):**
   - Triggers when the user is idle for $>5$ minutes (configurable).
   - Scans for broken tests, stale documentation, or code optimization opportunities.
   - Emits non-intrusive notification cards for user review upon return. Never interrupts active typing or active turns.
2. **Downtime Dreaming (Memory Distillation):**
   - Runs during idle downtime to process session logs in `sessions.db`.
   - Distills user preferences, project facts, and architectural insights into persistent semantic memory.
3. **Downtime Standby (Power Management):**
   - Suspends background loops and sleeps idle model lanes to conserve CPU, battery, and memory until user activity or a webhook wakes the agent.

---

## 3. The 5-Stage Agent Execution Pipeline

Every agent turn follows this strict execution lifecycle:

```
1. Intent & Skill Evaluation  ──>  2. Skill-Gap Fallback  ──>  3. Guarded Tool Execution  ──>  4. Verification  ──>  5. Autonomous Skill Synthesis
   (Classify & JIT Load)            (Research & Plan)          (Call➔Observe➔Eval➔Decide)        (State Check)        (Persist novel SKILL.md)
```

### The Tool Evaluation Contract:
- After every tool execution, the agent must evaluate:
  1. `status == 0`?
  2. Was non-empty data returned?
  3. Error classification if failed (*Permission*, *Timeout*, *Path Error*).
- **3-Strike Repetition Breaker:** Halts immediately if 2 consecutive identical calls fail, or 3 syntax variants fail without state progression.
- **Task-Aware Timeouts:** Standard tools (5–15s); Heavy compilations/builds (60–300s with structured timeout feedback).
