#!/usr/bin/env python3
"""
ARES Local Model Orchestrator Evaluation CLI Runner.
Usage:
    python tools/model_eval_runner.py
    python tools/model_eval_runner.py --models qwen2.5:3b qwen3.6:35b-mlx gemma4:31b-mlx
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Add project root to sys.path
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from core.evaluation.eval_suite import (
    run_orchestrator_evaluation_suite,
    load_latest_eval_results,
    generate_eval_markdown_report,
)


def main():
    parser = argparse.ArgumentParser(description="Run ARES Local Model Evaluation Benchmark")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["qwen2.5:3b", "qwen3.6:35b-mlx", "gemma4:31b-mlx"],
        help="List of model names to evaluate via Ollama",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:11434",
        help="Ollama base API URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--show-last",
        action="store_true",
        help="Display the latest evaluation results without re-running",
    )
    args = parser.parse_args()

    if args.show_last:
        latest = load_latest_eval_results()
        if not latest:
            print("No previous evaluation results found.")
            sys.exit(1)
        print(generate_eval_markdown_report(latest))
        return

    print("=" * 70)
    print("ARES LOCAL MODEL ORCHESTRATOR EVALUATION HARNESS")
    print("=" * 70)
    print(f"Target Models: {args.models}")
    print(f"Ollama Server: {args.url}")
    print("Rubric: 100 points across Reasoning, Tool Selection, Latency, Constraints, Memory, Error Recovery")
    print("=" * 70)

    summary = run_orchestrator_evaluation_suite(model_names=args.models, base_url=args.url)
    
    print(chr(10) + generate_eval_markdown_report(summary))


if __name__ == "__main__":
    main()
