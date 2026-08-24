# Local Model Orchestrator Evaluation Rubric

## Purpose
Score local models on suitability as the DEFAULT ORCHESTRATOR for ARES/Jaeger OS — the model that parses user intent, compiles task graphs, dispatches to lanes, and verifies results.

## Evaluation Criteria (100 points total)

### 1. Reasoning & Decomposition (25 pts)
- Can break complex requests into executable DAGs
- Identifies missing info vs. inferable context
- Handles multi-step workflows without losing state

### 2. Tool Selection & Schema Accuracy (20 pts)
- Picks correct tool for each subtask
- Constructs valid tool arguments (no hallucinated fields)
- Recovers from tool errors with corrected calls

### 3. Latency & Throughput (15 pts)
- Time to first token (target: <2s for 3b, <5s for 35b+)
- Tokens/second sustained
- Context window utilization efficiency

### 4. Instruction Following (15 pts)
- Obeys output format constraints (no markdown when told)
- Stops at completion (no runaway generation)
- Respects safety boundaries without false refusals

### 5. Memory & Context Retention (15 pts)
- Recalls earlier turns in multi-turn sessions
- Uses memory tools correctly (remember/recall/search)
- Maintains coherence across 10+ turn conversations

### 6. Error Recovery & Self-Correction (10 pts)
- Detects own mistakes from tool results
- Retries with fixes, not repeated failures
- Knows when to ask for clarification

## Test Suite

### Test 1: Simple Lookup (5 pts)
"what's the weather in Seattle?" → should call get_weather, not web_search

### Test 2: Multi-Step File Task (15 pts)
"find all Python files in skills/ with 'test' in the name, read the first one, and summarize what it tests"

### Test 3: Memory Round-Trip (10 pts)
1. "remember my favorite color is blue"
2. Later: "what's my favorite color?"

### Test 4: Tool Error Recovery (15 pts)
Give a malformed tool call scenario; model must read error and fix

### Test 5: Long Context Retention (15 pts)
10-turn conversation with embedded fact at turn 3, queried at turn 10

### Test 6: Orchestrator DAG Compile (20 pts)
"download the top 3 arxiv papers on RAG, extract their abstracts, and write a comparison table"

### Test 7: Output Constraint Compliance (10 pts)
"reply in one sentence, no markdown" — verify output

### Test 8: Clarification vs. Inference (10 pts)
"email Sam the deck" — should lookup_contact first, not guess address

## Scoring Rubric per Test

| Score | Meaning |
|-------|---------|
| 5 | Perfect — correct tool, valid args, correct output |
| 4 | Minor flaw (e.g., extra verbosity) but succeeded |
| 3 | Completed with one retry or clarification needed |
| 2 | Failed first attempt, succeeded after intervention |
| 1 | Partial — wrong tool or invalid args |
| 0 | Failed — crash, refusal, or hallucinated result |

## Minimum Thresholds for Orchestrator Role

| Model Size | Min Score | Max Latency (TFT) | Min Context |
|------------|-----------|-------------------|-------------|
| ≤7b | 60/100 | 2s | 32k |
| 8-34b | 70/100 | 5s | 64k |
| 35b+ | 80/100 | 10s | 128k |

## Local Models to Evaluate

1. **qwen2.5:3b** (1.9 GB) — small, fast, likely low score on complex tasks
2. **qwen3.6:35b-mlx** (21 GB) — mid-large, should handle orchestration
3. **gemma4:31b-mlx** (18 GB) — similar class to qwen3.6:35b
4. **nomic-embed-text** — embedding model only, NOT an LLM orchestrator

## Next Steps
Run each test against all 3 LLMs (skip nomic-embed), record scores, compute totals, recommend best local orchestrator.
