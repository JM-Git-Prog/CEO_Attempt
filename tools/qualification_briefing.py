"""Local-only, preemptible post-round qualification briefing job."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "qualification-briefing/v1"
LOCAL_MODELS = ("nuextract", "gpt-oss:20b", "qwen3-coder-next")


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


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


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


def discover_iterations(root: Path = ROOT) -> tuple[Path, ...]:
    qualification = root / "output" / "qualification"
    return tuple(sorted(
        (
            path for path in qualification.glob("20*")
            if path.is_dir() and (path / "summary.json").is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    ))


def _resolve_evidence_path(value: object, *, root: Path, iteration: Path) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    candidates = (path,) if path.is_absolute() else (root / path, iteration / path)
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)


def load_iteration(path: Path, root: Path = ROOT) -> dict:
    summary = _json(path / "summary.json")
    trial_paths: list[Path] = []
    for results in (summary.get("lane_results") or {}).values():
        for result in results or []:
            resolved = _resolve_evidence_path(
                result.get("evidence_path"), root=root, iteration=path,
            )
            if resolved:
                trial_paths.append(resolved)
    trial_paths.extend(path.glob("trials/*/trial-*.json"))
    trial_paths.extend(
        candidate for candidate in (path / "v11-e2e.json", path / "formal-v11-e2e.json")
        if candidate.is_file()
    )
    unique = tuple(dict.fromkeys(candidate.resolve() for candidate in trial_paths))
    return {"path": path.resolve(), "summary": summary, "trials": unique}


def build_fact_packet(iterations: list[dict], root: Path = ROOT) -> dict:
    if not iterations:
        raise ValueError("No completed qualification rounds")
    latest = iterations[0]
    previous = iterations[1] if len(iterations) > 1 else None
    occurrences: list[dict] = []
    for iteration in iterations:
        for trial_path in iteration["trials"]:
            try:
                trial = _json(trial_path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if trial.get("passed") is True:
                continue
            signatures = trial.get("failure_signatures") or []
            if not signatures and trial.get("failure_signature"):
                signatures = [{"signature": trial["failure_signature"]}]
            for signature in signatures:
                occurrences.append({
                    "signature": signature.get("signature") or trial.get("failure_signature"),
                    "stage": signature.get("stage"),
                    "rule": signature.get("rule"),
                    "detail": signature.get("detail"),
                    "session_id": trial.get("session_id"),
                    "evidence_path": _relative(trial_path, root),
                    "stage_evidence": (trial.get("stages") or {}).get(signature.get("stage")) or {},
                })
    counts = Counter(str(item["signature"]) for item in occurrences if item["signature"])
    latest_summary = latest["summary"]
    previous_summary = previous["summary"] if previous else {}
    latest_trials = len(latest["trials"])
    previous_trials = len(previous["trials"]) if previous else 0
    return {
        "schema_version": SCHEMA_VERSION,
        "latest_iteration": latest_summary.get("iteration_id") or latest["path"].name,
        "latest_summary_path": _relative(latest["path"] / "summary.json", root),
        "previous_iteration": previous_summary.get("iteration_id") if previous else None,
        "previous_summary_path": (
            _relative(previous["path"] / "summary.json", root) if previous else None
        ),
        "fingerprint": latest_summary.get("source_fingerprint_before"),
        "stale": bool(latest_summary.get("stale")),
        "passed": bool(latest_summary.get("passed")),
        "duration_seconds": latest_summary.get("duration_seconds"),
        "previous_duration_seconds": previous_summary.get("duration_seconds"),
        "round_trial_count": latest_trials,
        "trial_count_delta": latest_trials - previous_trials,
        "scheduler": latest_summary.get("scheduler") or {},
        "signature_counts": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))),
        "occurrences": occurrences,
    }


def _terminate(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def run_local_model(
    model: str,
    prompt: str,
    *,
    stop_requested: Callable[[], bool],
    timeout_seconds: float,
) -> tuple[str, str]:
    if model not in LOCAL_MODELS:
        raise ValueError(f"Unapproved briefing model: {model}")
    token_limits = {"nuextract": 192, "gpt-oss:20b": 320, "qwen3-coder-next": 384}
    request = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "keep_alive": 0,
        "options": {"temperature": 0.1, "num_predict": token_limits[model]},
    }
    if model == "nuextract":
        request["format"] = "json"
    child = (
        "import json,sys,urllib.request; "
        "payload=json.load(sys.stdin); "
        "request=urllib.request.Request('http://127.0.0.1:11434/api/generate', "
        "data=json.dumps(payload).encode('utf-8'), headers={'Content-Type':'application/json'}); "
        "response=json.loads(urllib.request.urlopen(request, timeout=600).read().decode('utf-8')); "
        "sys.stdout.buffer.write(str(response.get('response') or '').encode('utf-8'))"
    )
    environment = os.environ.copy()
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    with tempfile.TemporaryFile(mode="w+b") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", child], cwd=ROOT, env=environment,
            stdin=subprocess.PIPE, stdout=output, stderr=output,
            text=True, encoding="utf-8", errors="replace", shell=False,
        )
        assert process.stdin is not None
        process.stdin.write(json.dumps(request))
        process.stdin.close()
        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None:
            if stop_requested():
                _terminate(process)
                return "preempted", ""
            if time.monotonic() >= deadline:
                _terminate(process)
                return "timeout", ""
            time.sleep(0.25)
        output.seek(0)
        text = output.read().decode("utf-8", "replace").strip()
    return ("complete", text) if process.returncode == 0 and text else ("failed", text)


def _json_from_text(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _cite_draft(text: str, evidence_path: str) -> str:
    lines = []
    for line in text.strip().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "[evidence:" not in stripped:
            line += f" [evidence: {evidence_path}]"
        lines.append(line)
    return "\n".join(lines)


def render_briefing(facts: dict, prose_draft: str, extraction: dict | None) -> str:
    summary_path = facts["latest_summary_path"]
    previous_path = facts.get("previous_summary_path") or summary_path
    lines = [
        f"<!-- briefing-round: {facts['latest_iteration']} -->",
        "# Qualification BRIEFING",
        "",
        "> **UNVERIFIED LOCAL-MODEL DRAFT. Verify every cited artifact before acting.**",
        "",
        "## Deltas vs previous round",
        f"- Round trials: `{facts['round_trial_count']}`; delta: `{facts['trial_count_delta']:+d}`. "
        f"[evidence: {summary_path}] [evidence: {previous_path}]",
        f"- Duration: `{facts.get('duration_seconds')}` seconds; previous: "
        f"`{facts.get('previous_duration_seconds')}`. [evidence: {summary_path}] "
        f"[evidence: {previous_path}]",
        f"- Scheduler status: `{facts['scheduler'].get('status')}`; stale: `{facts['stale']}`. "
        f"[evidence: {summary_path}]",
        "",
        "## Signature counts",
    ]
    if facts["signature_counts"]:
        for signature, count in facts["signature_counts"].items():
            evidence = next(
                item["evidence_path"] for item in facts["occurrences"]
                if str(item["signature"]) == signature
            )
            lines.append(f"- `{signature}`: `{count}`. [evidence: {evidence}]")
    else:
        lines.append(f"- No real-trial failure signatures in the compared rounds. [evidence: {summary_path}]")
    lines.extend(["", "## Exact failing values"])
    if facts["occurrences"]:
        for item in facts["occurrences"][:30]:
            stage_value = json.dumps(item["stage_evidence"], sort_keys=True, default=str)
            if len(stage_value) > 700:
                stage_value = stage_value[:697] + "..."
            lines.append(
                f"- Session `{item.get('session_id')}` · `{item.get('signature')}` · "
                f"detail `{item.get('detail')}` · stage evidence `{stage_value}`. "
                f"[evidence: {item['evidence_path']}]"
            )
    else:
        lines.append(f"- None recorded. [evidence: {summary_path}]")
    extraction_note = json.dumps(extraction, sort_keys=True, default=str) if extraction else "unavailable"
    lines.extend([
        "", "## Ranked hypotheses / assumptions (unverified)",
        _cite_draft(prose_draft or "Local prose model unavailable; strong-model review required.", summary_path),
        "", "## Nuextract draft (unverified)",
        f"- `{extraction_note}` [evidence: {summary_path}]",
        "", "## Verification rule",
        f"- Do not act on this briefing until the cited evidence is independently checked. [evidence: {summary_path}]",
    ])
    return "\n".join(lines) + "\n"


def _log(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def run_briefing(
    *,
    root: Path = ROOT,
    log_path: Path | None = None,
    stop_requested: Callable[[], bool] = lambda: False,
    model_runner: Callable[..., tuple[str, str]] = run_local_model,
) -> dict:
    started = time.time()
    qualification = root / "output" / "qualification"
    briefing_path = qualification / "BRIEFING.md"
    draft_path = qualification / "DRAFT-PATCH.md"
    log_path = log_path or root / "data" / "flywheel" / "idle-jobs.log"
    should_stop = lambda: stop_requested() or _other_qualification_active(root)
    if should_stop():
        result = {"job": "briefing", "status": "preempted", "duration_seconds": 0.0}
        _log(log_path, {**result, "at_epoch": time.time()})
        return result
    rounds = [load_iteration(path, root) for path in discover_iterations(root)[:3]]
    if not rounds:
        result = {"job": "briefing", "status": "no_evidence", "duration_seconds": 0.0}
        _log(log_path, {**result, "at_epoch": time.time()})
        return result
    facts = build_fact_packet(rounds, root)
    marker = f"<!-- briefing-round: {facts['latest_iteration']} -->"
    if briefing_path.is_file() and draft_path.is_file() and marker in briefing_path.read_text(encoding="utf-8"):
        result = {"job": "briefing", "status": "skipped", "iteration_id": facts["latest_iteration"], "duration_seconds": 0.0}
        _log(log_path, {**result, "at_epoch": time.time()})
        return result
    model_facts = {
        "latest_iteration": facts["latest_iteration"],
        "latest_summary_path": facts["latest_summary_path"],
        "fingerprint": facts["fingerprint"],
        "round_trial_count": facts["round_trial_count"],
        "trial_count_delta": facts["trial_count_delta"],
        "scheduler": facts["scheduler"],
        "signature_counts": facts["signature_counts"],
        "occurrences": [
            {key: value for key, value in occurrence.items() if key != "stage_evidence"}
            for occurrence in facts["occurrences"][:12]
        ],
    }
    facts_json = json.dumps(model_facts, sort_keys=True, default=str)
    extract_status, extract_text = model_runner(
        "nuextract",
        "Extract exact numeric fields and signature counts from this JSON. Return JSON only:\n" + facts_json,
        stop_requested=should_stop, timeout_seconds=90,
    )
    if extract_status == "preempted" or should_stop():
        result = {"job": "briefing", "status": "preempted", "duration_seconds": round(time.time() - started, 3)}
        _log(log_path, {**result, "at_epoch": time.time()})
        return result
    extraction = _json_from_text(extract_text) if extract_status == "complete" else None
    prose_status, prose = model_runner(
        "gpt-oss:20b",
        "Using only the evidence packet below, write ranked hypotheses/assumptions and exactly one next probe. "
        "Tag every claim with [evidence: PATH]. Do not claim verification.\n" + facts_json,
        stop_requested=should_stop, timeout_seconds=180,
    )
    if prose_status == "preempted" or should_stop():
        result = {"job": "briefing", "status": "preempted", "duration_seconds": round(time.time() - started, 3)}
        _log(log_path, {**result, "at_epoch": time.time()})
        return result
    if prose_status != "complete":
        prose = ""
    draft_status, patch_draft = model_runner(
        "qwen3-coder-next",
        "Draft only a mechanical unified diff and focused test stubs suggested by this unverified evidence. "
        "If judgment is required, output NEEDS-JUDGMENT with reasons. Never claim the patch was applied.\n" + facts_json + "\nHYPOTHESES:\n" + prose,
        stop_requested=should_stop, timeout_seconds=180,
    )
    if draft_status == "preempted" or should_stop():
        result = {"job": "briefing", "status": "preempted", "duration_seconds": round(time.time() - started, 3)}
        _log(log_path, {**result, "at_epoch": time.time()})
        return result
    if draft_status != "complete":
        patch_draft = ""
    warnings = [status for status in (extract_status, prose_status, draft_status) if status != "complete"]
    briefing = render_briefing(facts, prose, extraction)
    draft = "\n".join([
        marker, "# DRAFT PATCH — NOT APPLIED", "",
        "> Unverified local qwen3-coder-next output. Strong-model review and Tier 0/1 are mandatory.",
        "", patch_draft or "NEEDS-JUDGMENT: local patch draft unavailable.", "",
        f"Evidence basis: `{facts['latest_summary_path']}`.",
    ])
    _atomic_write(briefing_path, briefing)
    _atomic_write(draft_path, draft)
    status = "complete_with_model_warning" if warnings else "complete"
    result = {
        "job": "briefing", "status": status, "warnings": warnings,
        "iteration_id": facts["latest_iteration"],
        "duration_seconds": round(time.time() - started, 3),
    }
    _log(log_path, {**result, "at_epoch": time.time()})
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--log", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    result = run_briefing(
        root=root,
        log_path=args.log.resolve() if args.log else root / "data" / "flywheel" / "idle-jobs.log",
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"complete", "complete_with_model_warning", "skipped", "preempted", "no_evidence"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
