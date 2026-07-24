"""Phase F0: append qualification trials to the passive flywheel corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
QUALIFICATION_ROOT = ROOT / "output" / "qualification"
CORPUS_PATH = ROOT / "data" / "flywheel" / "corpus.jsonl"
IDLE_LOG_PATH = ROOT / "data" / "flywheel" / "idle-jobs.log"
SCHEMA_VERSION = "flywheel-corpus/v1"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        ctypes.windll.kernel32.CloseHandle(process)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _other_qualification_active(root: Path) -> bool:
    lock = root / "output" / "qualification" / ".qualification.lock"
    try:
        pid = int(_json(lock).get("pid", -1))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return pid != os.getpid() and _pid_alive(pid)


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _iteration_dir(path: Path, qualification_root: Path) -> Path:
    for parent in path.parents:
        if parent.parent == qualification_root:
            return parent
    return path.parent


def discover_trials(qualification_root: Path = QUALIFICATION_ROOT) -> tuple[Path, ...]:
    paths = set(qualification_root.glob("*/v11-e2e.json"))
    paths.update(qualification_root.glob("*/formal-v11-e2e.json"))
    paths.update(qualification_root.glob("*/trials/*/trial-*.json"))
    for path in qualification_root.glob("*.json"):
        try:
            if _json(path).get("schema_version") == "v11-e2e-result/v1":
                paths.add(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return tuple(sorted((path for path in paths if path.is_file()), key=lambda p: p.as_posix()))


def _lane_for(path: Path, raw: dict, summary: dict) -> str:
    if path.parent.parent.name == "trials":
        return path.parent.name
    formal = (summary.get("scheduler") or {}).get("formal") or {}
    if path.name == "formal-v11-e2e.json" and formal.get("lane"):
        return str(formal["lane"])
    for lane, results in (summary.get("lane_results") or {}).items():
        for result in results or []:
            if Path(str(result.get("evidence_path", ""))).name == path.name:
                return str(lane)
    return str(raw.get("lane") or "local-default")


def _repair_actions(session: dict) -> list:
    for key in ("repair_actions_applied", "repair_actions", "repair_history"):
        value = session.get(key)
        if isinstance(value, list):
            return value
    return []


def build_record(path: Path, root: Path = ROOT) -> dict:
    raw = _json(path)
    iteration = _iteration_dir(path, root / "output" / "qualification")
    summary_path = iteration / "summary.json"
    summary = _json(summary_path) if summary_path.is_file() else {}
    session_id = raw.get("session_id")
    session_dir = root / "output" / str(session_id) if session_id else None
    session_path = session_dir / "session.json" if session_dir else None
    session = _json(session_path) if session_path and session_path.is_file() else {}
    plan_path = session_dir / "floor_plan_v1.json" if session_dir else None
    plan = _json(plan_path) if plan_path and plan_path.is_file() else session.get("floor_plan")
    evidence_path = _relative(path, root)
    evidence_bytes = path.read_bytes()
    record_id = hashlib.sha256(evidence_path.encode("utf-8")).hexdigest()
    warnings = []
    repairs = _repair_actions(session)
    if not repairs:
        warnings.append("repair_actions_not_recorded")
    if plan is None:
        warnings.append("plan_not_built")
    record = {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id,
        "source_evidence_path": evidence_path,
        "source_evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        "session_id": session_id,
        "prompt_id": raw.get("prompt_id"),
        "qualification_mode": raw.get("qualification_mode", "real"),
        "description": raw.get("canonical_prompt"),
        "plan": plan,
        "world_contract": session.get("world_contract"),
        "per_gate_verdicts": raw.get("stages") or {},
        "failure_signatures": raw.get("failure_signatures") or (
            [raw["failure_signature"]] if raw.get("failure_signature") else []
        ),
        "repair_actions_applied": repairs,
        "model_lane": _lane_for(path, raw, summary),
        "source_fingerprint": summary.get("source_fingerprint_before"),
        "timestamps": {
            "trial_started_at_epoch": raw.get("started_at_epoch"),
            "trial_finished_at_epoch": raw.get("finished_at_epoch"),
            "duration_seconds": raw.get("duration_seconds"),
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        },
        "extraction_warnings": warnings,
    }
    return record


def _existing_ids(corpus_path: Path) -> set[str]:
    if not corpus_path.is_file():
        return set()
    ids: set[str] = set()
    for line in corpus_path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("record_id"):
            ids.add(str(value["record_id"]))
    return ids


def _log(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def extract_corpus(
    *,
    root: Path = ROOT,
    corpus_path: Path = CORPUS_PATH,
    log_path: Path = IDLE_LOG_PATH,
    stop_requested: Callable[[], bool] = lambda: False,
    max_records: int | None = None,
) -> dict:
    started = time.time()
    should_stop = lambda: stop_requested() or _other_qualification_active(root)
    if should_stop():
        result = {
            "status": "preempted", "appended": 0, "skipped": 0,
            "errors": 0, "duration_seconds": 0.0,
        }
        _log(log_path, {**result, "at_epoch": time.time()})
        return result
    lock = corpus_path.with_suffix(corpus_path.suffix + ".lock")
    corpus_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        result = {"status": "busy", "appended": 0, "skipped": 0, "errors": 0}
        _log(log_path, {**result, "at_epoch": time.time()})
        return result
    os.close(fd)
    appended = skipped = errors = 0
    try:
        existing = _existing_ids(corpus_path)
        qualification_root = root / "output" / "qualification"
        with corpus_path.open("a", encoding="utf-8") as corpus:
            for path in discover_trials(qualification_root):
                if should_stop():
                    break
                if max_records is not None and appended >= max_records:
                    break
                record_id = hashlib.sha256(_relative(path, root).encode("utf-8")).hexdigest()
                if record_id in existing:
                    skipped += 1
                    continue
                try:
                    record = build_record(path, root)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    errors += 1
                    _log(log_path, {
                        "status": "record_error", "path": _relative(path, root),
                        "error": type(exc).__name__, "at_epoch": time.time(),
                    })
                    continue
                corpus.write(json.dumps(record, sort_keys=True, separators=(",", ":"), default=str) + "\n")
                corpus.flush()
                os.fsync(corpus.fileno())
                existing.add(record["record_id"])
                appended += 1
        status = "preempted" if should_stop() else "complete"
        result = {
            "status": status, "appended": appended, "skipped": skipped,
            "errors": errors, "duration_seconds": round(time.time() - started, 3),
        }
        _log(log_path, {**result, "at_epoch": time.time()})
        return result
    finally:
        lock.unlink(missing_ok=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--max-records", type=int)
    args = parser.parse_args(argv)
    if args.max_records is not None and args.max_records <= 0:
        parser.error("max-records must be positive")
    args.root = args.root.resolve()
    args.corpus = (args.corpus or args.root / "data" / "flywheel" / "corpus.jsonl").resolve()
    args.log = (args.log or args.root / "data" / "flywheel" / "idle-jobs.log").resolve()
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = extract_corpus(
        root=args.root, corpus_path=args.corpus, log_path=args.log,
        max_records=args.max_records,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"complete", "preempted"} else 2


if __name__ == "__main__":
    raise SystemExit(main())


# --- Bench ingestion (writes to corpus-bench.jsonl, same record_id formula as bench/ingest_bench_to_corpus.py) ---

BENCH_CORPUS_PATH = ROOT / "data" / "flywheel" / "corpus-bench.jsonl"
BENCH_DIR = ROOT / "bench"
PROMPT_SET_PATH = ROOT / "data" / "flywheel" / "prompt-set-v1.json"


def _bench_prompt_texts() -> dict[str, str]:
    try:
        doc = json.loads(PROMPT_SET_PATH.read_text(encoding="utf-8"))
        raw = doc.get("prompts") if isinstance(doc, dict) else doc
        return {
            p.get("id", f"p{i+1:03d}"): p.get("prompt") or p.get("description") or p.get("text", "")
            for i, p in enumerate(raw) if isinstance(p, dict)
        }
    except (OSError, json.JSONDecodeError):
        return {}


def ingest_bench(
    *,
    root: Path = ROOT,
    corpus_path: Path | None = None,
    log_path: Path = IDLE_LOG_PATH,
    stop_requested: Callable[[], bool] = lambda: False,
) -> dict:
    """Ingest bench/results-*.json into corpus-bench.jsonl.

    Uses the same record_id = sha256(results-file|lane|prompt_id)[:24] as
    bench/ingest_bench_to_corpus.py so both writers dedup against each other.
    """
    corpus_path = corpus_path or (root / "data" / "flywheel" / "corpus-bench.jsonl")
    started = time.time()
    texts = _bench_prompt_texts()
    corpus_path.parent.mkdir(parents=True, exist_ok=True)

    existing: set[str] = set()
    if corpus_path.is_file():
        for line in corpus_path.read_text(encoding="utf-8").splitlines():
            try:
                existing.add(json.loads(line).get("record_id", ""))
            except (json.JSONDecodeError, ValueError):
                continue

    bench_dir = root / "bench"
    results_files = sorted(bench_dir.glob("results-*.json"))
    appended = skipped = errors = 0
    buf: list[str] = []

    for rf in results_files:
        if stop_requested():
            break
        try:
            doc = json.loads(rf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors += 1
            continue
        for lane, lane_data in (doc.get("lanes") or {}).items():
            for row in lane_data.get("rows") or []:
                pid = row.get("prompt_id", "?")
                rid = hashlib.sha256(f"{rf.name}|{lane}|{pid}".encode()).hexdigest()[:24]
                if rid in existing:
                    skipped += 1
                    continue
                if not isinstance(row.get("plan"), (dict, list)):
                    continue  # error/timeout rows carry no plan
                legal = row.get("status") == "legal"
                record = json.dumps({
                    "schema_version": "flywheel-corpus/bench-v1",
                    "record_id": rid,
                    "description": texts.get(pid, ""),
                    "prompt_id": pid,
                    "plan": row["plan"],
                    "per_gate_verdicts": {"plan": "passed" if legal else "failed"},
                    "failure_signatures": [f"plan/validator/{c}" for c in row.get("blockers", [])],
                    "model_lane": lane,
                    "qualification_mode": "bench",
                    "pipeline_era": "pre-inversion",
                    "timestamps": {"extracted_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                    "source_results_file": rf.name,
                }, separators=(",", ":"), sort_keys=True)
                buf.append(record)
                existing.add(rid)
                appended += 1

    if buf:
        with corpus_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(buf) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    result = {
        "job": "ingest_bench", "status": "complete", "appended": appended,
        "skipped": skipped, "errors": errors,
        "duration_seconds": round(time.time() - started, 3),
    }
    _log(log_path, {**result, "at_epoch": time.time()})
    return result
