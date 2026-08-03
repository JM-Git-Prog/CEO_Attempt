"""CLI entry point for the E2E World Test Kit.

Usage:
    python -m tests.e2e.world_test_kit run --prompt "A cozy cabin in the woods"
    python -m tests.e2e.world_test_kit run --prompt "Modern office" --layers conversation,navigation
    python -m tests.e2e.world_test_kit check  # Just verify config and model availability
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from tests.e2e.world_test_kit.config import load_wtk_config
from tests.e2e.world_test_kit.orchestrator import WorldTestOrchestrator


def main() -> int:
    """CLI main entry point."""
    parser = argparse.ArgumentParser(
        prog="world_test_kit",
        description="E2E World Test Kit — LLM-driven playtester for V16 pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # 'run' command
    run_parser = subparsers.add_parser("run", help="Execute a full playtest run")
    run_parser.add_argument(
        "--prompt", "-p",
        required=True,
        help="World description prompt to submit",
    )
    run_parser.add_argument(
        "--layers",
        help="Comma-separated list of layers to run (default: all enabled)",
    )
    run_parser.add_argument(
        "--config",
        help="Path to world_test_kit.yaml config file",
    )
    run_parser.add_argument(
        "--json", action="store_true",
        help="Output full JSON report instead of summary",
    )
    run_parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )

    # 'check' command
    check_parser = subparsers.add_parser(
        "check", help="Verify config and model availability"
    )
    check_parser.add_argument(
        "--config",
        help="Path to world_test_kit.yaml config file",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    # Set up logging
    level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "check":
        return _cmd_check(args)
    elif args.command == "run":
        return _cmd_run(args)

    return 1


def _cmd_check(args: argparse.Namespace) -> int:
    """Verify configuration and model availability."""
    config = load_wtk_config(args.config)
    print(f"Config loaded: playtester={config.playtester_model}, vision={config.vision_model}")
    print(f"Server URL: {config.server_url}")
    print(f"Pass threshold: {config.pass_threshold}, Individual minimum: {config.individual_minimum}")

    # Check Ollama availability
    try:
        import httpx
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{config.ollama_base_url}/api/tags")
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                print(f"Ollama available — {len(models)} models loaded")
                has_playtester = any(config.playtester_model in m for m in models)
                has_vision = any(config.vision_model in m for m in models)
                print(f"  Playtester ({config.playtester_model}): {'✓' if has_playtester else '✗ not found'}")
                print(f"  Vision ({config.vision_model}): {'✓' if has_vision else '✗ not found'}")
            else:
                print(f"Ollama returned HTTP {resp.status_code}")
    except Exception as e:
        print(f"Ollama not available: {e}")
        print("  Will run in scripted mode (auto-approve, skip subjective evaluation)")

    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Execute a full playtest run."""
    config = load_wtk_config(args.config)
    orchestrator = WorldTestOrchestrator(config)

    layers = args.layers.split(",") if args.layers else None

    report = orchestrator.run(args.prompt, layers=layers)

    if args.json:
        print(report.to_json())
    else:
        orchestrator._reporter.print_summary(report)

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
