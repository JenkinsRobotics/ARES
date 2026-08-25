# Dual-Axis Cognitive & Autonomy Architecture (Next-Gen Standard)

## 1. Executive Summary & Industry Comparison
Most industry agent architectures (e.g. Cursor, Claude Code, OpenAI Operator) collapse agent behavior into a **single, flat mode dropdown** (e.g., "Chat" vs "Agent" vs "Deep Research").

ARES & JaegerAI implement a **Dual-Orthogonal State Matrix**:
1. **The Autonomy Axis (HOW the agent executes):** `Manual` ↔ `Plan` ↔ `Auto`
2. **The Cognitive Mindset Axis (WHAT the brain prioritizes):** `Focus` ↔ `Wondering` ↔ `Research` ↔ `Dream` ↔ `Audit` ↔ `Standby`

This enables combinatorial capabilities impossible in flat systems (e.g., *Planning a Deep Research query before execution*, or *Proactive Wondering with Step-by-Step Approvals*).

---

## 2. The $3 \times 6$ Operational Matrix

| Cognitive Mindset | `Plan` Mode (Architect First) | `Manual` Mode (Interactive Gated) | `Auto` Mode (Autonomous Loop) |
| :--- | :--- | :--- | :--- |
| **`🎯 Focus`** | Generates detailed implementation plan & diff preview for user sign-off. | Step-by-step interactive pair programming with confirmation on file writes. | Unbroken execution loop towards the immediate prompt goal. |
| **`🌌 Wondering`** | Proactively identifies code debts/test gaps and produces an improvement proposal. | Notifies user of discovered suggestions via UI cards before acting. | Auto-implements background cleanups and self-heals failing tests during idle. |
| **`🔬 Research`** | Outlines research topics, target URLs, and citations before launching broad crawls. | Interactive multi-turn research, querying user for source prioritization. | Deep recursive web and codebase synthesis, compiling a finalized report. |
| **`🌙 Dream`** | Summarizes recent turns and proposes memory updates for review. | Step-by-step memory pruning and episodic-to-semantic consolidation. | Automatic background memory distillation and vector index maintenance. |
| **`🛡️ Audit`** | Outlines security vulnerabilities, lint issues, and SAIF/TCC compliance rules. | Interactive triage of security warnings with user-guided remediation. | Full automated repo compliance audit and report generation. |
| **`💤 Standby`** | Ready to accept a prompt; no background token consumption. | Low-power idle state waiting for user interaction. | Wake-on-trigger (Webhook/Cron) only. |

---

## 3. Protocol & Runtime Alignment Rules

1. **Orthogonal State Separation:**
   - Autonomy mode (`manual`, `plan`, `auto`) is owned per-turn / per-session.
   - Cognitive mode (`focus`, `wondering`, `research`, `dream`, `audit`, `standby`) is an instance-level cognitive posture.
2. **Non-Intrusive Background Handoffs:**
   - In `Wondering` or `Dream` mode, autonomous discoveries must never clobber an active draft in `Focus` mode; they emit background cards or notifications.
3. **Safety Inheritance:**
   - Destructive actions (deleting files, dropping databases, modifying critical keys) ALWAYS require user confirmation unless explicitly running in a sandboxed, isolated environment.
