"""
ARES Local Model Orchestrator Evaluation Suite & Benchmark Runner.

Enhanced with Prompt Engineering, System Role Framing, and Semantic Keyword Synonyms
tailored for local LLMs (Qwen, Gemma, Llama, MLX engines).

Features:
- Standardized Orchestrator System Role to align local model verbage.
- Semantic synonym matching (e.g. lookup/find/search, four/4).
- Preamble stripping for clean constraint validation.
- Strict Sequential Lifecycle (Load -> Test -> Unload -> Cooldown).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are the ARES System Orchestrator — an autonomous execution and tool routing agent. "
    "Respond with high precision, extreme conciseness, and strict adherence to instructions. "
    "Do not include conversational filler, pleasantries, or markdown unless explicitly requested."
)

EVALUATION_CRITERIA = {
    "reasoning": {"name": "Reasoning & DAG Decomposition", "max_points": 25},
    "tool_accuracy": {"name": "Tool Selection & Schema Accuracy", "max_points": 20},
    "latency": {"name": "Latency & Throughput", "max_points": 15},
    "instruction_following": {"name": "Instruction Following & Output Constraints", "max_points": 15},
    "memory_retention": {"name": "Memory & Context Retention", "max_points": 15},
    "error_recovery": {"name": "Error Recovery & Self-Correction", "max_points": 10},
}

TEST_CASES = [
    {
        "id": "T1_simple_lookup",
        "category": "tool_accuracy",
        "prompt": "What's the weather in Seattle? Respond with only the tool name you would call (e.g. get_weather, web_search, none).",
        "expected_any": ["get_weather", "weather", "fetch_weather"],
        "points": 5,
        "description": "Selects specific domain tool over generic web search",
    },
    {
        "id": "T2_file_task",
        "category": "tool_accuracy",
        "prompt": "List the first 5 files in the skills/ directory. Output format: '<count> <first_filename>' (e.g. '5 skill_1.js').",
        "expected_any": ["5", "five", "skill", ".js", ".py", ".md", ".json"],
        "points": 15,
        "description": "Multi-step file system inspection and summarization",
    },
    {
        "id": "T3_memory_roundtrip",
        "category": "memory_retention",
        "prompt": "Remember that my test favorite color is cobalt blue. Acknowledge with the single word 'stored'.",
        "expected_any": ["stored"],
        "points": 10,
        "followup": {
            "prompt": "What was my test favorite color?",
            "expected_any": ["blue", "cobalt"],
        },
        "description": "Store and recall discrete fact across multi-turn session",
    },
    {
        "id": "T4_output_constraint",
        "category": "instruction_following",
        "prompt": "Reply in exactly one sentence with no markdown: what is 2+2?",
        "expected_any": ["4", "four"],
        "no_markdown": True,
        "one_sentence": True,
        "points": 10,
        "description": "Strict output formatting and punctuation compliance",
    },
    {
        "id": "T5_clarification",
        "category": "reasoning",
        "prompt": "I need to email Sam the report. What is your required first step before sending? (e.g. lookup contact or get email address)",
        "expected_any": ["lookup", "contact", "email address", "find", "search", "address book", "recipient", "ask"],
        "points": 10,
        "description": "Identifies missing parameters instead of guessing addresses",
    },
    {
        "id": "T6_reasoning_dag",
        "category": "reasoning",
        "prompt": "If I have 3 files and need to process each one independently, then merge all 3 results into one output, how many total distinct steps is that? (Reply with the number)",
        "expected_any": ["4", "four", "4 steps", "four steps"],
        "points": 15,
        "description": "Decomposes parallel execution graph and reduction step",
    },
    {
        "id": "T7_context_retention",
        "category": "memory_retention",
        "prompt": "In this conversation, the secret access code is Falcon77. Acknowledge with the single word 'noted'.",
        "expected_any": ["noted"],
        "points": 15,
        "followup": {
            "prompt": "What was the secret access code mentioned earlier?",
            "expected_any": ["falcon77", "falcon 77"],
        },
        "description": "Retains embedded token across intermediate turns",
    },
    {
        "id": "T8_error_handling",
        "category": "error_recovery",
        "prompt": "A tool call to read '/data/logs.txt' fails with error 'file not found'. What is your immediate diagnostic or recovery action?",
        "expected_any": ["search", "find", "locate", "check", "list", "verify", "alternate", "path", "explore", "directory", "inspect"],
        "points": 10,
        "description": "Recovers gracefully from tool failure with alternative discovery",
    },
]


def ares_evals_dir() -> Path:
    base = Path(os.environ.get("ARES_HOME", Path.home() / ".ares"))
    eval_dir = base / "evals"
    eval_dir.mkdir(parents=True, exist_ok=True)
    return eval_dir


def unload_model(model_name: str, base_url: str = "http://localhost:11434") -> bool:
    """Explicitly unload model from VRAM."""
    logger.info("Unloading model %s...", model_name)
    try:
        subprocess.run(["ollama", "stop", model_name], capture_output=True, timeout=10)
    except Exception:
        pass
    try:
        endpoint = f"{base_url.rstrip('/')}/api/generate"
        payload = {"model": model_name, "keep_alive": 0}
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            pass
    except Exception:
        pass
    time.sleep(1.5)
    return True


def unload_all_active_models() -> None:
    """Stop any active model running in Ollama."""
    try:
        res = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=5)
        lines = res.stdout.strip().splitlines()
        if len(lines) > 1:
            for l in lines[1:]:
                parts = l.split()
                if parts:
                    m_name = parts[0]
                    subprocess.run(["ollama", "stop", m_name], capture_output=True, timeout=5)
    except Exception:
        pass
    time.sleep(1.0)


def warmup_model(model_name: str, base_url: str = "http://localhost:11434") -> bool:
    """Ensure clean VRAM, then warm up the target model exclusively."""
    unload_all_active_models()
    logger.info("Warming up model %s...", model_name)
    try:
        endpoint = f"{base_url.rstrip('/')}/api/generate"
        payload = {"model": model_name, "prompt": "ready check", "stream": False}
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True
    except Exception as exc:
        logger.warning("Warmup failed for %s: %s", model_name, exc)
        return False


def call_ollama(
    model: str,
    prompt: str,
    base_url: str = "http://localhost:11434",
    timeout: float = 180.0,
    history: Optional[List[Dict[str, str]]] = None,
    system_prompt: Optional[str] = ORCHESTRATOR_SYSTEM_PROMPT,
) -> Tuple[bool, str, float, float, Dict[str, Any]]:
    """
    Call Ollama /api/chat with aligned system prompt.
    Returns: (success, output_text, elapsed_sec, ttft_sec, raw_meta)
    """
    t0 = time.perf_counter()
    endpoint = f"{base_url.rstrip('/')}/api/chat"

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.05,
            "num_predict": 512,
        },
    }

    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.perf_counter() - t0
            msg_obj = data.get("message", {})
            content = msg_obj.get("content", "").strip()
            if not content and "thinking" in msg_obj:
                content = msg_obj["thinking"].strip()
            eval_count = data.get("eval_count", 0)
            eval_duration_ns = data.get("eval_duration", 0)
            ttft = (data.get("prompt_eval_duration", 0) / 1e9) or (elapsed * 0.3)
            tok_per_sec = (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns else 0

            return True, content, elapsed, ttft, {
                "eval_count": eval_count,
                "tokens_per_sec": round(tok_per_sec, 1),
                "ttft_sec": round(ttft, 2),
            }
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        logger.warning("Ollama call failed for %s: %s", model, exc)
        return False, "", elapsed, 0.0, {"error": str(exc)}


def _clean_preamble(text: str) -> str:
    """Strip common conversational preambles generated by local models."""
    cleaned = text.strip()
    # Strip phrases like "Sure! ", "Certainly, ", "Here is...", "To answer your question:"
    cleaned = re.sub(r"^(sure|certainly|of course|here is|here's|to answer your question|as requested)[!,\.:]?\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def evaluate_test_case(
    model: str,
    test: Dict[str, Any],
    caller_fn: Callable = call_ollama,
    base_url: str = "http://localhost:11434",
) -> Dict[str, Any]:
    """Execute a single rubric test case against a model with semantic synonym alignment."""
    prompt = test["prompt"]
    max_pts = test["points"]
    expected_matches = [m.lower() for m in test.get("expected_any", [test.get("expected_contains", "")]) if m]

    success, output, elapsed, ttft, meta = caller_fn(model, prompt, base_url=base_url)

    if not success:
        return {
            "test_id": test["id"],
            "category": test["category"],
            "score": 0,
            "max_points": max_pts,
            "latency_sec": round(elapsed, 2),
            "ttft_sec": 0,
            "status": "failed",
            "notes": f"API call failed: {meta.get('error', 'unknown')}",
            "output_preview": "",
        }

    output_lower = output.lower()
    cleaned_output = _clean_preamble(output)
    score = 0
    notes_parts = []

    # Semantic Keyword & Synonym Matching
    matched = any(exp in output_lower for exp in expected_matches)
    if matched:
        score = max_pts
        notes_parts.append("correct")
    else:
        score = max_pts // 2
        notes_parts.append(f"partial (missing {expected_matches[:3]})")

    # Output constraint checks
    if test.get("no_markdown"):
        if "**" in output or "```" in output or "#" in output or "- " in output:
            score = max(0, score - 2)
            notes_parts.append("[markdown violation]")

    if test.get("one_sentence"):
        sentences = [s.strip() for s in re.split(r"[.!?]+", cleaned_output) if s.strip()]
        if len(sentences) > 1:
            score = max(0, score - 2)
            notes_parts.append("[multi-sentence]")

    # Multi-turn followup verification
    if "followup" in test and score >= max_pts // 2:
        followup = test["followup"]
        exp_followup = [m.lower() for m in followup.get("expected_any", [followup.get("expected_contains", "")]) if m]
        history = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": output},
        ]
        s2, out2, el2, _, _ = caller_fn(model, followup["prompt"], base_url=base_url, history=history)
        if s2 and any(exp in out2.lower() for exp in exp_followup):
            notes_parts.append("+followup_ok")
        else:
            score = max(0, score - 3)
            notes_parts.append("+followup_fail")

    return {
        "test_id": test["id"],
        "category": test["category"],
        "score": score,
        "max_points": max_pts,
        "latency_sec": round(elapsed, 2),
        "ttft_sec": meta.get("ttft_sec", round(ttft, 2)),
        "tokens_per_sec": meta.get("tokens_per_sec", 0),
        "status": "passed" if score >= max_pts * 0.7 else "partial" if score > 0 else "failed",
        "notes": " ".join(notes_parts),
        "output_preview": output[:180].replace(chr(10), " "),
    }


def evaluate_model(
    model_name: str,
    base_url: str = "http://localhost:11434",
    caller_fn: Callable = call_ollama,
) -> Dict[str, Any]:
    """
    Run full evaluation suite for a single model following strict load -> test -> unload cycle.
    """
    print(f"\n{'='*60}")
    print(f"EVALUATING MODEL: {model_name}")
    print(f"{'='*60}")

    # 1. Warm up model exclusively
    warmup_model(model_name, base_url=base_url)

    results = []
    total_score = 0
    max_score = 0
    latencies = []
    ttfts = []

    try:
        # 2. Run all rubric tests
        for test in TEST_CASES:
            print(f"  -> Running {test['id']}...")
            res = evaluate_test_case(model_name, test, caller_fn=caller_fn, base_url=base_url)
            results.append(res)
            total_score += res["score"]
            max_score += res["max_points"]
            if res["latency_sec"] > 0:
                latencies.append(res["latency_sec"])
            if res["ttft_sec"] > 0:
                ttfts.append(res["ttft_sec"])
            print(f"     Score: {res['score']}/{res['max_points']} ({res['status']}) - {res['latency_sec']}s")
    finally:
        # 3. Always unload model before moving to next model
        print(f"  -> Unloading {model_name} from VRAM...")
        unload_model(model_name, base_url=base_url)

    percentage = round((total_score / max_score * 100), 1) if max_score > 0 else 0.0
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    avg_ttft = round(sum(ttfts) / len(ttfts), 2) if ttfts else 0.0

    is_small = "3b" in model_name.lower() or "1b" in model_name.lower() or "7b" in model_name.lower()
    min_pct = 60.0 if is_small else 70.0
    verdict = "PASS" if percentage >= min_pct else "FAIL"

    return {
        "model": model_name,
        "total_score": total_score,
        "max_score": max_score,
        "percentage": percentage,
        "verdict": verdict,
        "avg_latency_sec": avg_latency,
        "avg_ttft_sec": avg_ttft,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }


def run_orchestrator_evaluation_suite(
    model_names: Optional[List[str]] = None,
    base_url: str = "http://localhost:11434",
) -> Dict[str, Any]:
    """
    Run evaluation suite sequentially across designated local models.
    Each model is loaded, evaluated, and unloaded before the next one starts.
    """
    if not model_names:
        model_names = ["qwen2.5:3b", "qwen3.6:35b-mlx", "gemma4:31b-mlx"]

    all_results = []
    for idx, m in enumerate(model_names, 1):
        print(f"\n[{idx}/{len(model_names)}] Starting evaluation cycle for {m}...")
        try:
            res = evaluate_model(m, base_url=base_url)
            all_results.append(res)
        except Exception as exc:
            logger.error("Failed to evaluate %s: %s", m, exc)
            all_results.append({
                "model": m,
                "total_score": 0,
                "max_score": 100,
                "percentage": 0.0,
                "verdict": "ERROR",
                "notes": str(exc),
                "results": [],
            })

    best_model = None
    if all_results:
        valid_results = [r for r in all_results if r.get("verdict") in ("PASS", "FAIL")]
        if valid_results:
            best_model = max(valid_results, key=lambda x: x["percentage"])["model"]

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "models_evaluated": len(all_results),
        "recommended_orchestrator": best_model,
        "results": all_results,
    }

    save_eval_results(summary)
    return summary


def generate_eval_markdown_report(summary: Dict[str, Any]) -> str:
    """Format evaluation results into a Markdown report."""
    lines = [
        "# 🏆 Local Model Orchestrator Benchmark & Evaluation Report",
        f"*Evaluation completed at: {summary.get('timestamp', 'N/A')}*",
        "",
        "> Scores local models against the ARES/Jaeger OS Orchestrator Rubric.",
        "",
        "## 📊 Summary Scorecard",
        "| Model | Score | Max | Percentage | Avg Latency | Avg TTFT | Verdict |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for r in summary.get("results", []):
        m = r.get("model", "unknown")
        score = r.get("total_score", 0)
        max_pts = r.get("max_score", 100)
        pct = r.get("percentage", 0.0)
        lat = f"{r.get('avg_latency_sec', 0)}s"
        ttft = f"{r.get('avg_ttft_sec', 0)}s"
        verdict = f"**{r.get('verdict', 'N/A')}**"
        lines.append(f"| `{m}` | {score} | {max_pts} | **{pct:.1f}%** | {lat} | {ttft} | {verdict} |")

    rec = summary.get("recommended_orchestrator")
    if rec:
        lines.extend([
            "",
            f"### 🎯 Recommended Default Orchestrator: `{rec}`",
            "",
        ])

    lines.extend([
        "## 📋 Detailed Test Case Breakdown",
        "",
    ])

    for r in summary.get("results", []):
        m = r.get("model", "unknown")
        lines.extend([
            f"### Model: `{m}` ({r.get('percentage', 0):.1f}%)",
            "| Test ID | Category | Points | Status | Latency | Output Preview |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for t in r.get("results", []):
            tid = t.get("test_id", "")
            cat = t.get("category", "")
            pts = f"{t.get('score', 0)}/{t.get('max_points', 0)}"
            status = t.get("status", "")
            lat = f"{t.get('latency_sec', 0)}s"
            preview = t.get("output_preview", "").replace("|", "/")[:60]
            lines.append(f"| `{tid}` | {cat} | {pts} | {status} | {lat} | {preview} |")
        lines.append("")

    return chr(10).join(lines)


def save_eval_results(summary: Dict[str, Any]) -> Tuple[Path, Path]:
    """Persist evaluation results in JSON and Markdown formats."""
    eval_dir = ares_evals_dir()
    json_path = eval_dir / "model_eval_results.json"
    md_path = eval_dir / "evaluation_report.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    md_report = generate_eval_markdown_report(summary)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_report)

    ws_json = Path("/Users/matthewjenkins/GitHub/ARES/model_eval_results.json")
    try:
        with open(ws_json, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    return json_path, md_path


def load_latest_eval_results() -> Optional[Dict[str, Any]]:
    eval_dir = ares_evals_dir()
    json_path = eval_dir / "model_eval_results.json"
    if not json_path.exists():
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load eval results: %s", exc)
        return None
