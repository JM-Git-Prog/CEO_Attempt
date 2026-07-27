"""Repair Modelfiles that say "FROM None", then register the newest good one.

train_probe.py looked for the .gguf inside the run folder, but Unsloth writes
it to a sibling "<run>_gguf" folder. The glob found nothing, so the Modelfile
was written as the literal text "FROM None" and every `ollama create` failed -
which is why two trained models exist and neither was ever benched. The
generator is fixed; this repairs the ones already on disk.

Only rewrites a Modelfile whose target does not exist AND for which a real
.gguf can be found. Never deletes anything.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRAINED = ROOT / "bench" / "trained"


def find_gguf(run_dir: Path):
    hit = next(run_dir.glob("*.gguf"), None)
    if hit:
        return hit
    sibling = run_dir.parent / f"{run_dir.name}_gguf"
    if sibling.exists():
        return next(sibling.glob("*.gguf"), None)
    return None


def main() -> int:
    if not TRAINED.exists():
        print(f"no trained folder at {TRAINED}")
        return 1

    repaired = []
    healthy = []
    for run_dir in sorted(TRAINED.iterdir()):
        if not run_dir.is_dir() or run_dir.name.endswith("_gguf"):
            continue
        modelfile = run_dir / "Modelfile"
        gguf = find_gguf(run_dir)
        current = modelfile.read_text(encoding="utf-8").strip() if modelfile.exists() else ""
        target = current[5:].strip() if current.startswith("FROM ") else ""

        if target and target != "None" and Path(target).exists():
            healthy.append(run_dir.name)
            print(f"  OK       {run_dir.name}  -> {Path(target).name}")
            continue
        if gguf is None:
            print(f"  NO GGUF  {run_dir.name}  (training never produced one - skipping)")
            continue
        modelfile.write_text(f"FROM {gguf}\n", encoding="utf-8")
        check = modelfile.read_text(encoding="utf-8").strip()
        if check != f"FROM {gguf}":
            print(f"  FAILED   {run_dir.name}  (re-read did not match what was written)")
            return 1
        repaired.append((run_dir.name, modelfile, gguf))
        print(f"  REPAIRED {run_dir.name}  was {current!r} -> {gguf.name}")

    if not repaired and not healthy:
        print("\nnothing registrable found.")
        return 1

    newest = None
    if repaired:
        newest = repaired[-1]
    elif healthy:
        name = healthy[-1]
        newest = (name, TRAINED / name / "Modelfile", find_gguf(TRAINED / name))

    name, modelfile, gguf = newest
    print(f"\nRegistering the newest trained model ({name}) as planner-probe-v1...")
    print(f"  ollama create planner-probe-v1 -f \"{modelfile}\"")
    proc = subprocess.run(["ollama", "create", "planner-probe-v1", "-f", str(modelfile)],
                          capture_output=True, text=True, timeout=1800)
    print((proc.stdout or "").strip()[-800:])
    if proc.returncode != 0:
        print("OLLAMA CREATE FAILED:")
        print((proc.stderr or "").strip()[-800:])
        return 1
    print("  registered OK")

    verify = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=60)
    if "planner-probe-v1" not in (verify.stdout or ""):
        print("  BUT it does not appear in `ollama list` - not trusting that.")
        return 1
    print("  verified present in `ollama list`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
