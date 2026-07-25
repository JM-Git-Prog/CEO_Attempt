"""Stage C - small LoRA hyperparameter sweep (cheap-first: filtered through
the FAST holdout check, not a slow live exam, before anything is trusted).

Trains a short, deliberately-chosen list of hyperparameter combinations -
NOT a full grid - each under its OWN Ollama model name, so the live
planner-probe-v1 lane is never overwritten mid-sweep. Ranks candidates on
the holdout set (Stage B) and, only if a candidate actually beats the
current baseline combo, writes the winner's hyperparameters to
bench/best-hparams.json. train_probe.py already reads that file as its new
default (Stage D) - so the next normal flywheel training cycle picks the
winner up automatically. No further wiring needed anywhere else.

This is slow - each combo is a full training run on the 4090. Run it
occasionally, not every cycle.

Shells out to train_probe.py and holdout_eval.py exactly the way
run_chain.py and flywheel_loop.py already shell out to their neighbors -
kept consistent rather than importing them as Python modules.

Usage:
  python bench\\hparam_sweep.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
BEST_HPARAMS_FILE = BENCH / "best-hparams.json"
SWEEP_LOG = BENCH / "hparam-sweep-log.json"
PROGRESS = BENCH / "training-progress.json"

# A short, deliberately spread list - not a grid. Each combo after
# "baseline" varies ONE thing from today's default (rank=16, alpha=16,
# dropout=0.0, epochs=3, lr=2e-4), so a win is traceable to one change,
# never a confound of several at once.
COMBOS = [
    {"name": "baseline",     "rank": 16, "alpha": 16, "dropout": 0.0,  "epochs": 3, "lr": 2e-4},
    {"name": "higher-rank",  "rank": 32, "alpha": 32, "dropout": 0.0,  "epochs": 3, "lr": 2e-4},
    {"name": "more-epochs",  "rank": 16, "alpha": 16, "dropout": 0.0,  "epochs": 5, "lr": 2e-4},
    {"name": "lower-lr",     "rank": 16, "alpha": 16, "dropout": 0.0,  "epochs": 3, "lr": 1e-4},
    {"name": "with-dropout", "rank": 16, "alpha": 16, "dropout": 0.05, "epochs": 3, "lr": 2e-4},
]


def _train(combo: dict, model_name: str) -> int:
    r = subprocess.run(
        [sys.executable, str(BENCH / "train_probe.py"),
         "--rank", str(combo["rank"]), "--alpha", str(combo["alpha"]),
         "--dropout", str(combo["dropout"]), "--epochs", str(combo["epochs"]),
         "--lr", str(combo["lr"]), "--model-name", model_name,
         "--run-name", f"sweep-{combo['name']}"],
        cwd=str(ROOT),
    )
    return r.returncode


def _holdout(model_name: str) -> dict:
    summary_path = BENCH / f"hparam-sweep-holdout-{model_name}.json"
    subprocess.run(
        [sys.executable, str(BENCH / "holdout_eval.py"),
         "--lane", model_name, "--summary-out", str(summary_path)],
        cwd=str(ROOT),
    )
    if not summary_path.exists():
        return {}
    return json.loads(summary_path.read_text(encoding="utf-8"))


def main() -> int:
    results = []
    for combo in COMBOS:
        model_name = f"planner-probe-sweep-{combo['name']}"
        print(f"\n=== SWEEP '{combo['name']}' -> {model_name} ===", flush=True)

        rc = _train(combo, model_name)
        if rc != 0:
            print(f"  train_probe FAILED rc={rc} - skipping this combo")
            results.append({**combo, "model_name": model_name, "status": "train_failed"})
            continue

        progress = json.loads(PROGRESS.read_text(encoding="utf-8")) if PROGRESS.exists() else {}
        modelfile = progress.get("modelfile")
        if progress.get("stage") != "done" or not modelfile:
            print("  no modelfile after training - skipping registration/eval")
            results.append({**combo, "model_name": model_name, "status": "no_modelfile"})
            continue

        r2 = subprocess.run(["ollama", "create", model_name, "-f", modelfile], timeout=600)
        if r2.returncode != 0:
            print(f"  ollama create FAILED rc={r2.returncode} - skipping eval")
            results.append({**combo, "model_name": model_name, "status": "register_failed"})
            continue

        holdout = _holdout(model_name)
        rate = (holdout.get("result") or {}).get("legal_rate")
        print(f"  holdout legal_rate={rate}")
        results.append({
            **combo, "model_name": model_name, "status": "ok",
            "holdout_legal_rate": rate,
            "holdout_legal": (holdout.get("result") or {}).get("legal"),
            "holdout_total": (holdout.get("result") or {}).get("total"),
        })

    ranked = sorted(
        [r for r in results if r.get("status") == "ok"],
        key=lambda r: r.get("holdout_legal_rate") if r.get("holdout_legal_rate") is not None else -1,
        reverse=True,
    )
    SWEEP_LOG.write_text(json.dumps({
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": results, "ranked": [r["name"] for r in ranked],
    }, indent=1), encoding="utf-8")

    print("\n=== SWEEP LEADERBOARD (holdout legal_rate, best first) ===")
    for r in ranked:
        rate = r["holdout_legal_rate"] or 0
        print(f"  {r['name']:14s} {round(100*rate):3d}%  ({r['holdout_legal']}/{r['holdout_total']})")

    if not ranked:
        print("\nNo combo finished cleanly - best-hparams.json left untouched.")
        return 1

    winner = ranked[0]
    baseline = next((r for r in results if r["name"] == "baseline" and r.get("status") == "ok"), None)
    baseline_rate = (baseline or {}).get("holdout_legal_rate") or 0
    if winner["name"] != "baseline" and (winner["holdout_legal_rate"] or 0) <= baseline_rate:
        print(f"\nBest combo '{winner['name']}' did not beat baseline "
              f"({round(100*baseline_rate)}%) - best-hparams.json left untouched.")
        return 0
    if winner["name"] == "baseline":
        print("\nBaseline won its own sweep - best-hparams.json left untouched "
              "(nothing to change).")
        return 0

    new_defaults = {"rank": winner["rank"], "alpha": winner["alpha"],
                     "dropout": winner["dropout"], "epochs": winner["epochs"], "lr": winner["lr"]}
    BEST_HPARAMS_FILE.write_text(json.dumps(new_defaults, indent=1), encoding="utf-8")
    print(f"\nWinner: '{winner['name']}' ({round(100*winner['holdout_legal_rate'])}% holdout, "
          f"baseline was {round(100*baseline_rate)}%) -> written to {BEST_HPARAMS_FILE}")
    print("The next normal flywheel training cycle will pick this up automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
