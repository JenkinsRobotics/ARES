#!/usr/bin/env python3
"""
Local Model Orchestrator Evaluation Runner
Tests each local LLM sequentially: load → test → unload → next model
"""

import subprocess
import json
import time
import sys

LOCAL_MODELS = [
    {"name": "qwen2.5:3b", "size": "3b"},
    {"name": "qwen3.6:35b-mlx", "size": "35b"},
    {"name": "gemma4:31b-mlx", "size": "31b"},
]

TEST_CASES = [
    {
        "id": "T1_simple_lookup",
        "prompt": "What's the weather in Seattle? Respond with only the tool name you would call.",
        "expected": "get_weather",
        "points": 5
    },
    {
        "id": "T2_file_task",
        "prompt": "List the first 5 files in the skills/ directory. Respond with just the count and first filename.",
        "expected_contains": "skills",
        "points": 15
    },
    {
        "id": "T3_memory_roundtrip",
        "prompt": "Remember my test favorite color is blue. Confirm with 'stored'.",
        "expected": "stored",
        "points": 10,
        "followup": {"prompt": "What's my test favorite color?", "expected": "blue"}
    },
    {
        "id": "T4_output_constraint",
        "prompt": "Reply in exactly one sentence with no markdown: what is 2+2?",
        "expected": "4",
        "no_markdown": True,
        "one_sentence": True,
        "points": 10
    },
    {
        "id": "T5_clarification",
        "prompt": "I need to email Sam the report. What's your first step?",
        "expected_contains": "lookup",
        "points": 10
    },
    {
        "id": "T6_reasoning",
        "prompt": "If I have 3 files and need to process each one, then merge results, how many distinct steps is that?",
        "expected": "3",
        "points": 15
    },
    {
        "id": "T7_context_retention",
        "prompt": "The secret code is Falcon77. Acknowledge with 'noted'.",
        "expected": "noted",
        "followup": {"prompt": "What was the secret code?", "expected": "Falcon77"},
        "points": 15
    },
    {
        "id": "T8_error_handling",
        "prompt": "What would you do if a tool call fails with 'file not found'?",
        "expected_contains": "search",
        "points": 20
    }
]

def run_ollama_command(cmd):
    """Run an ollama CLI command."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "timeout"
    except Exception as e:
        return False, "", str(e)

def load_model(model_name):
    """Load a model into memory (warm it up)."""
    print(f"  Loading {model_name}...")
    # Run a trivial prompt to load the model
    success, out, err = run_ollama_command(f'ollama run {model_name} "ready"')
    if success:
        print(f"  ✓ {model_name} loaded")
        return True
    print(f"  ✗ Failed to load {model_name}: {err[:100]}")
    return False

def unload_model(model_name):
    """Stop the model server for this model."""
    print(f"  Unloading {model_name}...")
    # ollama doesn't have explicit unload, but we can stop the server
    # For now, just wait and let memory pressure handle it
    # Alternative: kill ollama serve and restart (too aggressive)
    success, out, err = run_ollama_command('ollama ps')
    if success:
        print(f"  Active models: {out[:200]}")
    return True

def run_test(model_name, test):
    """Run a single test against a model."""
    print(f"    Running {test['id']}...")
    
    prompt = test['prompt']
    expected = test.get('expected', '')
    expected_contains = test.get('expected_contains', '')
    
    # Call model via ollama
    cmd = f'ollama run {model_name} "{prompt}"'
    success, output, err = run_ollama_command(cmd)
    
    if not success:
        print(f"      ✗ Model call failed: {err[:100]}")
        return 0, test['points'], "call_failed"
    
    output_lower = output.lower()
    expected_lower = expected.lower() if expected else ""
    
    # Score based on test type
    score = 0
    notes = ""
    
    if expected_contains:
        if expected_contains.lower() in output_lower:
            score = test['points']
            notes = "correct"
        else:
            score = test['points'] // 2
            notes = f"partial (missing '{expected_contains}')"
    elif expected:
        if expected_lower in output_lower:
            score = test['points']
            notes = "correct"
        else:
            score = test['points'] // 2
            notes = f"partial (expected '{expected}')"
    else:
        score = test['points'] // 2
        notes = "manual_review_needed"
    
    # Check constraints
    if test.get('no_markdown') and ('**' in output or '```' in output):
        score = max(0, score - 2)
        notes += " [markdown violation]"
    
    if test.get('one_sentence'):
        sentences = [s.strip() for s in output.replace('\n', ' ').split('.') if s.strip()]
        if len(sentences) > 1:
            score = max(0, score - 2)
            notes += " [multi-sentence]"
    
    # Handle followup tests
    if 'followup' in test and score >= test['points'] // 2:
        followup = test['followup']
        cmd2 = f'ollama run {model_name} "{followup["prompt"]}"'
        success2, output2, err2 = run_ollama_command(cmd2)
        if success2:
            if followup.get('expected', '').lower() in output2.lower():
                notes += " +followup_ok"
            else:
                score = max(0, score - 3)
                notes += " +followup_fail"
    
    print(f"      Score: {score}/{test['points']} - {notes}")
    return score, test['points'], notes

def evaluate_model(model):
    """Run all tests against one model."""
    print(f"\n{'='*60}")
    print(f"EVALUATING: {model['name']} ({model['size']})")
    print(f"{'='*60}")
    
    # Load model
    if not load_model(model['name']):
        print(f"  SKIPPING {model['name']} - failed to load")
        return None
    
    # Give model time to warm up
    time.sleep(2)
    
    total_score = 0
    max_score = 0
    results = []
    
    for test in TEST_CASES:
        score, max_pts, notes = run_test(model['name'], test)
        total_score += score
        max_score += max_pts
        results.append({
            "test_id": test['id'],
            "score": score,
            "max": max_pts,
            "notes": notes
        })
    
    # Unload model
    unload_model(model['name'])
    
    # Wait between models
    time.sleep(3)
    
    percentage = (total_score / max_score * 100) if max_score > 0 else 0
    return {
        "model": model['name'],
        "size": model['size'],
        "total_score": total_score,
        "max_score": max_score,
        "percentage": round(percentage, 1),
        "results": results
    }

def main():
    print("="*60)
    print("LOCAL MODEL ORCHESTRATOR EVALUATION")
    print("="*60)
    print(f"Models to test: {[m['name'] for m in LOCAL_MODELS]}")
    print(f"Test cases: {len(TEST_CASES)}")
    print(f"Strategy: load → test → unload (one model at a time)")
    print("="*60)
    
    all_results = []
    
    for i, model in enumerate(LOCAL_MODELS):
        print(f"\n[Model {i+1}/{len(LOCAL_MODELS)}]")
        result = evaluate_model(model)
        if result:
            all_results.append(result)
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"{'Model':<25} {'Score':<10} {'Max':<10} {'%':<10} {'Verdict':<15}")
    print("-"*60)
    
    for r in all_results:
        # Thresholds: 3b needs 60%, 30b+ needs 70%
        min_pct = 60 if '3b' in r['model'] else 70
        verdict = "PASS" if r['percentage'] >= min_pct else "FAIL"
        print(f"{r['model']:<25} {r['total_score']:<10} {r['max_score']:<10} {r['percentage']:<10.1f} {verdict:<15}")
    
    if all_results:
        best = max(all_results, key=lambda x: x['percentage'])
        print(f"\nRECOMMENDATION: {best['model']} ({best['percentage']:.1f}%)")
        
        # Save results
        with open('workspace/model_eval_results.json', 'w') as f:
            json.dump(all_results, f, indent=2)
        print(f"\nResults saved to workspace/model_eval_results.json")
    
    return all_results

if __name__ == "__main__":
    main()
