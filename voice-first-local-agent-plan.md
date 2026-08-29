# ARES Voice-First Local Agent — Build Plan

## Goal

Make ARES usable in real-time voice mode with a local model for conversation,
while delegating tool use and heavy reasoning to cloud models. The operator
talks; the local model listens and responds; when tools or deep thought are
needed, the request fans out to a cloud backend and the result comes back
through the same voice interface.

## Current State

**What works now:**
- Voice pipeline: Kokoro TTS + Whisper STT + barge-in + wake-word + follow-up windows
- VoiceController in `interfaces/tui/voice_session.py` — full duplex mic/speak loop
- Mode switching: `normal` (local + voice), `high` (bigger model, no voice), `deep-sleep`
- Agent loop: autonomous runner, work ledger, continuation, delegation
- Completions rail: background delegations surface on next idle turn
- Domain router: topic-shift detection, memory recall
- Heartbeat: standing checklist, idle supervisor
- ARES interop: cross-agent profile, MCP config bridge

**What's missing:**
- No multi-model routing (every request hits one model)
- No "local voice + cloud tools" split
- No persistent perception loop (watch screen, detect changes)
- Self-improvement cycle not wired in runtime
- Deep Think queue runner not connected to mode switch

## Architecture: Voice-First Local + Cloud Delegation

```
Operator speaks
     |
     v
Whisper STT (local, always-on)
     |
     v
Local Model (gemma-4-e4b, voice mode)
  +----------------------------------+
  |  Simple chat -> respond directly |
  |  Needs tools -> delegate to cloud|
  |  Needs deep thought -> queue DT  |
  +----------------------------------+
     |                    |
     |              Cloud Model (Anthropic/OpenAI/Ollama-cloud)
     |              - tool execution
     |              - deep reasoning
     |              - code generation
     |                    |
     v                    v
Kokoro TTS (local)  <---+
     |
     v
Operator hears response
```

## Step-by-Step Plan

### Phase 1: Voice Mode Hardening (Day 1-2)

**1.1 Verify voice pipeline works end-to-end**
- Files: `jaeger_ai/interfaces/tui/voice_session.py`, `jaeger_ai/modules/jaeger_kokoro_tts.py`, `jaeger_ai/modules/jaeger_whisper_stt.py`
- Test: `./jaeger --voice` from CLI
- Fix any import errors or missing deps
- Verify wake-word, follow-up window, barge-in all function

**1.2 Add voice-mode config to `jaeger.toml`**
- File: `jaeger.toml`
- Add `[voice]` section with defaults:
  - wake_word = true
  - follow_up = true
  - barge_in = true
  - follow_up_seconds = 10.0
  - stt_mode = "two_pass"
  - local_model = "gemma-4-e4b-it-q4_k_m"

**1.3 Ensure `normal` mode is the voice+local default**
- File: `jaeger_ai/core/runtime/modes.py`
- Verify MODES["normal"] has voice=True and points to the e4b model
- Already correct — just confirm it boots properly

### Phase 2: Cloud Delegation from Voice (Day 2-4)

**2.1 Create `jaeger_ai/core/runtime/lane_router.py`**
- New file. The core routing logic:
  - LOCAL = "local" (gemma-4-e4b, voice-enabled)
  - CLOUD = "cloud" (ollama-cloud / anthropic / openai)
  - DEEP_THINK = "deep" (26B model, queued)
  - classify(text, has_tools) -> lane choice based on intent

**2.2 Wire lane_router into the agent loop**
- File: `jaeger_ai/core/runtime/dispatch.py`
- In `prepare_turn_text()`, after domain/ledger blocks, add a routing hint
- The hint tells the local model: "if you need tools, emit a delegation marker"
- The completion rail already handles background delegation results

**2.3 Create `jaeger_ai/core/runtime/cloud_delegate.py`**
- New file. Handles the actual fan-out:
  - Receives a delegation marker from the local model
  - Sends the request to the configured cloud provider
  - Returns the result through the completions rail
  - The local model then speaks the summary via TTS

**2.4 Update `jaeger_ai/modules/jaeger_agent.py`**
- Add `CLOUD_DELEGATE` topic to WATCH
- Wire the delegation marker into the agent's tool schema so the local
  model can request cloud assistance as a "tool call"

### Phase 3: Always-On Perception (Day 4-6)

**3.1 Create `jaeger_ai/core/runtime/perception.py`**
- New file. A lightweight loop that runs alongside voice:
  - Periodic system health check (CPU, memory, disk)
  - Calendar/event awareness (morning briefing)
  - Notification monitoring
  - Runs on the heartbeat cadence (every 5 min idle, immediate on wake)

**3.2 Wire perception into heartbeat**
- File: `jaeger_ai/core/runtime/heartbeat.py`
- Add perception checks to the default checklist
- If something needs attention, inject a turn into the voice session

**3.3 Add proactive notification**
- When perception detects something worth mentioning:
  - If voice is active: speak it
  - If voice is idle: push a system notification + queue for next wake

### Phase 4: Self-Improvement Loop (Day 6-8)

**4.1 Wire skill_note -> skill_review -> deep_think pipeline**
- File: `jaeger_ai/core/runtime/idle_supervisor.py`
- On idle, check skill_notes for patterns of failures
- Auto-propose deep_think tasks for skills with >3 issue notes
- Already partially exists — connect the dots

**4.2 Connect deep-sleep mode to the Deep Think queue**
- File: `jaeger_ai/core/runtime/modes.py`
- `_engage_deep_think()` is currently a no-op stub
- Wire it to actually drain the queue when the 26B model is loaded

### Phase 5: Polish and Testing (Day 8-10)

**5.1 Integration test: full voice loop**
- Speak a simple question -> local model responds
- Speak a tool request -> delegation to cloud -> result spoken back
- Test barge-in during cloud delegation
- Test wake-word + follow-up window

**5.2 Config validation**
- `jaeger.toml` voice section validates on boot
- Missing deps give clear error messages
- Mode switching preserves voice state correctly

**5.3 Documentation**
- Update `docs/` with voice-mode setup guide
- Add `VOICE_PIPELINE.md` describing the architecture

## Files Likely to Change

| File | Change |
|------|--------|
| `jaeger_ai/core/runtime/lane_router.py` | NEW — intent classification + routing |
| `jaeger_ai/core/runtime/cloud_delegate.py` | NEW — cloud model fan-out |
| `jaeger_ai/core/runtime/perception.py` | NEW — always-on perception loop |
| `jaeger_ai/core/runtime/dispatch.py` | MODIFY — add routing hint to turn prep |
| `jaeger_ai/core/runtime/modes.py` | MODIFY — wire deep-sleep to DT queue |
| `jaeger_ai/core/runtime/heartbeat.py` | MODIFY — add perception checks |
| `jaeger_ai/core/runtime/idle_supervisor.py` | MODIFY — wire skill review pipeline |
| `jaeger_ai/modules/jaeger_agent.py` | MODIFY — add cloud delegation topic |
| `jaeger.toml` | MODIFY — add [voice] config section |
| `jaeger_ai/interfaces/tui/voice_session.py` | MODIFY — add cloud result injection |

## Risks and Tradeoffs

1. **Latency**: Cloud delegation adds 2-10s round-trip. The local model should
   acknowledge immediately ("Let me look that up...") while the cloud works.
   This is the same pattern Siri/Alexa use.

2. **Context continuity**: The local model won't see the cloud's full tool output,
   only a summary. We need a compaction step that distills the cloud result
   into a speakable summary before TTS.

3. **Cost**: Cloud model calls cost money. The router should be conservative —
   only delegate when tools or deep reasoning are genuinely needed. Simple
   chat stays local and free.

4. **Wake-word accuracy**: Whisper's wake-word detection is good but not perfect.
   The follow-up window (10s after reply) mitigates this — the user can
   continue without repeating the wake word.

5. **Model swap time**: Switching between normal and high mode takes 60-90s.
   Voice mode should stay on the local model and delegate rather than swap.

## Open Questions

1. Which cloud provider to default to? (Ollama-cloud is already configured;
   Anthropic/OpenAI would need API keys)
2. Should the local model be able to call tools directly, or always delegate?
   (Recommendation: always delegate — keeps the local model fast and simple)
3. How to handle cloud failures gracefully in voice mode? (Fallback: local
   model apologizes and offers to retry)
4. Should perception loop run when voice is off? (Recommendation: yes, via
   heartbeat — voice is just the output channel)

## Validation Commands

```bash
# Phase 1: Voice pipeline
./jaeger --voice

# Phase 2: Cloud delegation
./jaeger --voice  # then ask a tool question

# Phase 3: Perception
# Check heartbeat logs for perception entries

# Phase 4: Self-improvement
jaeger skills review  # should auto-propose from skill notes

# Phase 5: Integration
pytest tests/ -k "voice or lane or delegation"
```