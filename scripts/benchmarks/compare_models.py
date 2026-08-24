#!/usr/bin/env python3
"""Simple local model comparison - one prompt, each model, fair timing."""

import subprocess
import time
import sys

MODELS = ["kai:latest", "qwen3.6:35b-mlx"]

PROMPT = """You are a coding assistant. Solve this step by step:

A function f(n) returns:
- f(0) = 1
- f(1) = 1  
- f(n) = f(n-1) + 2*f(n-2) for n >= 2

What is f(10)? Show your work."""

def run_model(model):
    """Run one model, return (time_sec, response, tokens_est)."""
    start = time.time()
    try:
        result = subprocess.run(
            ["ollama", "run", model, PROMPT],
            capture_output=True,
            text=True,
            timeout=120
        )
        elapsed = time.time() - start
        output = result.stdout.strip()
        # Rough token estimate: ~4 chars per token
        tokens = len(output) // 4
        return elapsed, output, tokens
    except subprocess.TimeoutExpired:
        return 120, "[TIMEOUT]", 0
    except Exception as e:
        return 0, f"[ERROR: {e}]", 0

def main():
    print("=" * 60)
    print("LOCAL MODEL COMPARISON")
    print("=" * 60)
    print(f"Prompt: {PROMPT[:80]}...")
    print("=" * 60)
    
    results = []
    for model in MODELS:
        print(f"\n🔄 Running {model}...")
        elapsed, response, tokens = run_model(model)
        results.append((model, elapsed, response, tokens))
        print(f"   Time: {elapsed:.1f}s | Tokens: ~{tokens}")
        print(f"   Response preview: {response[:200]}...")
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"{'Model':<25} {'Time':<10} {'Tokens/s':<10} {'Answer'}")
    print("-" * 60)
    
    for model, elapsed, response, tokens in results:
        tokens_per_sec = tokens / elapsed if elapsed > 0 else 0
        # Extract answer
        answer = "f(10) = ?"
        if "273" in response:
            answer = "✓ f(10) = 273"
        elif "f(10)" in response:
            import re
            match = re.search(r"f\(10\)\s*=\s*(\d+)", response)
            if match:
                answer = f"f(10) = {match.group(1)}"
        
        print(f"{model:<25} {elapsed:<10.1f} {tokens_per_sec:<10.1f} {answer}")
    
    print("=" * 60)

if __name__ == "__main__":
    main()
