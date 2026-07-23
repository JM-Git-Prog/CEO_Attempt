"""Serialized continuous qualification for the current working tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlparse
from urllib.request import urlopen

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "output" / "qualification"
DEFAULT_LANES_CONFIG = ROOT / ".kiro" / "specs" / "llm-driven-upbge-runtime" / "lanes.json"
DEFAULT_FLYWHEEL_CORPUS = ROOT / "data" / "flywheel" / "corpus.jsonl"
DEFAULT_FLYWHEEL_LOG = ROOT / "data" / "flywheel" / "idle-jobs.log"
DEFAULT_AGENT_ACTIVE_FILE = DEFAULT_OUTPUT / ".agent-turn-active"
DEFAULT_FLYWHEEL_IDLE_SECONDS = 600.0
DEFAULT_READINESS_RECHECK_SECONDS = 60.0
INCLUDE_ROOTS = ("src", "tests", "tools", ".kiro/specs/llm-driven-upbge-runtime")
INCLUDE_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".md", ".toml"}
EXCLUDED_PARTS = {".git", ".kirograph", "output", "__pycache__", ".pytest_cache", ".hypothesis"}
SAFE_ENV = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "PYTHONUTF8",
    "PYTHONIOENCODING", "OLLAMA_HOST", "COMFYUI_URL", "NO_PROXY",
}
SAFE_OVERRIDE_ENV = {
    "QUALIFICATION_MOCK_E2E", "OLLAMA_URL", "OPENAI_API_URL", "OPENAI_API_KEY",
    "LLM_MODEL", "OLLAMA_NUM_PARALLEL", "COMFYUI_ENABLED", "IMAGE_API_URL", "IMAGE_API_KEY",
}
MOCK_E2E_ENV = {
    "QUALIFICATION_MOCK_E2E": "1",
    "OLLAMA_URL": "http://127.0.0.1:9",
    "OPENAI_API_URL": "",
    "OPENAI_API_KEY": "",
    "COMFYUI_ENABLED": "0",
    "IMAGE_API_URL": "",
    "IMAGE_API_KEY": "",
}
DEFAULT_LANE = "local-llama31"
DEFAULT_TRIAL_WORKERS = 2
MIN_RATCHET_TRIALS = 5
ROLLING_WINDOW = 10
EARLY_STOP_FAILURES = 3
STUCK_FAILURES = 5
DEFAULT_BUDGET_HOURS = 8.0
K3_MIN_FREE_VRAM_MIB = 16_384
REAL_TRIAL_ENV = {"OLLAMA_NUM_PARALLEL": "2"}
PASSING_STAGE_STATUSES = {"passed", "not_applicable"}


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class CommandEvidence(FrozenModel):
    name: str
    argv: tuple[str, ...]
    started_at_epoch: float
    duration_seconds: float
    returncode: int | None
    timed_out: bool
    passed: bool
    stdout_tail: str
    stderr_tail: str


class IterationEvidence(FrozenModel):
    schema_version: Literal["qualification-iteration/v1"] = "qualification-iteration/v1"
    iteration_id: str
    mode: str
    started_at_epoch: float
    finished_at_epoch: float
    duration_seconds: float
    source_fingerprint_before: str
    source_fingerprint_after: str
    stale: bool
    changed_files: tuple[str, ...]
    commands: tuple[CommandEvidence, ...]
    mock_e2e_result: dict | None
    e2e_result: dict | None
    lane_results: dict[str, tuple[dict, ...]] = Field(default_factory=dict)
    scheduler: dict = Field(default_factory=dict)
    qualified: bool = False
    stop_condition: str | None = None
    regression_delta: dict
    passed: bool


def _safe_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _canonical_json(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def relevant_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for root_name in INCLUDE_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        candidates = (root,) if root.is_file() else root.rglob("*")
        for path in candidates:
            if not path.is_file() or path.suffix.lower() not in INCLUDE_SUFFIXES:
                continue
            relative = path.relative_to(ROOT)
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            files.append(path)
    return tuple(sorted(files, key=lambda value: value.as_posix().lower()))


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in relevant_files():
        relative = path.relative_to(ROOT).as_posix().encode()
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


class ProcessLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    @staticmethod
    def _alive(pid: int) -> bool:
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
        except (OSError, ProcessLookupError, ValueError):
            return False

    def __enter__(self) -> "ProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                pid = int(payload.get("pid", -1))
            except Exception:
                pid = -1
            if pid > 0 and self._alive(pid):
                raise RuntimeError(f"qualification loop already running with pid {pid}")
            self.path.unlink(missing_ok=True)
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(self.fd, _canonical_json({"pid": os.getpid(), "created": time.time()}).encode())
        os.fsync(self.fd)
        return self

    def __exit__(self, *_args) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.path.unlink(missing_ok=True)


def _sanitized_environment(overrides: dict[str, str] | None = None) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV}
    for key, value in (overrides or {}).items():
        if key.upper() not in SAFE_OVERRIDE_ENV:
            raise ValueError(f"Unsafe qualification environment override: {key}")
        environment[key] = value
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def run_command(
    name: str,
    argv: list[str],
    timeout: float,
    env_overrides: dict[str, str] | None = None,
) -> CommandEvidence:
    started = time.time()
    returncode: int | None = None
    timed_out = False
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            env=_sanitized_environment(env_overrides),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
        returncode = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    except OSError as exc:
        stderr = f"{type(exc).__name__}: {exc}"
    return CommandEvidence(
        name=name,
        argv=tuple(argv),
        started_at_epoch=started,
        duration_seconds=round(time.time() - started, 3),
        returncode=returncode,
        timed_out=timed_out,
        passed=returncode == 0 and not timed_out,
        stdout_tail=stdout[-12000:],
        stderr_tail=stderr[-12000:],
    )


def command_plan(mode: str, e2e_result_path: Path) -> list[tuple[str, list[str]]]:
    python = sys.executable
    commands: list[tuple[str, list[str]]] = []
    if mode != "e2e-only":
        commands.extend([
            ("compileall", [python, "-m", "compileall", "-q", "src", "tools"]),
            ("node-check", ["node", "--check", "src/web/static/app.js"]),
            ("full-tests", [python, "-m", "pytest", "tests", "-q"]),
        ])
    if mode == "full":
        commands.append((
            "mock-v11-e2e",
            [
                python, "tools/v11_e2e_adapter.py", "--result",
                str(e2e_result_path.parent / "mock-v11-e2e.json"),
            ],
        ))
    if mode == "e2e-only":
        commands.append((
            "fresh-v11-e2e",
            [python, "tools/v11_e2e_adapter.py", "--result", str(e2e_result_path)],
        ))
    return commands


def _tier_statuses(evidence: IterationEvidence) -> dict[str, str]:
    commands = {command.name: command for command in evidence.commands}
    tier_zero_names = ("compileall", "node-check", "full-tests")
    present = [commands.get(name) for name in tier_zero_names]
    if not any(present):
        tier_zero = "not_run"
    elif all(command is not None and command.passed for command in present):
        tier_zero = "pass"
    else:
        tier_zero = "fail"

    if evidence.mode != "full":
        tier_one = "not_run"
    else:
        mock_command = commands.get("mock-v11-e2e")
        tier_one = "pass" if (
            mock_command is not None
            and mock_command.passed
            and evidence.mock_e2e_result
            and evidence.mock_e2e_result.get("passed") is True
        ) else "fail"
    return {"t0": tier_zero, "t1": tier_one}


def _empty_scoreboard() -> dict:
    return {
        "schema_version": "qualification-scoreboard/v1",
        "best": None,
        "current": None,
        "fingerprints": {},
        "lane_winners": {},
        "verdict": "INDETERMINATE",
    }


def _load_scoreboard(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty_scoreboard()
    if not isinstance(value, dict) or value.get("schema_version") != "qualification-scoreboard/v1":
        return _empty_scoreboard()
    value.setdefault("fingerprints", {})
    value.setdefault("lane_winners", {})
    value.setdefault("best", None)
    return value


def _load_lanes_config(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid qualification lanes config: {path}") from exc
    if payload.get("schema_version") != "qualification-lanes/v1":
        raise ValueError("Unsupported qualification lanes schema")
    names: set[str] = set()
    for lane in payload.get("lanes") or []:
        name = str(lane.get("name") or "")
        if not name or name in names:
            raise ValueError(f"Invalid or duplicate qualification lane: {name!r}")
        names.add(name)
        environment = lane.get("env") or {}
        if not isinstance(environment, dict) or any(
            key.upper() not in SAFE_OVERRIDE_ENV or not isinstance(value, str)
            for key, value in environment.items()
        ):
            raise ValueError(f"Unsafe environment in qualification lane: {name}")
        if lane.get("remote"):
            if lane.get("enabled") is not False:
                raise ValueError(f"Remote qualification lane must ship disabled: {name}")
            if lane.get("provider") != "ollama-pro" or set(environment) != {"LLM_MODEL"}:
                raise ValueError(f"Only approved Ollama Pro cloud lanes are permitted: {name}")
            authorization = lane.get("authorization") or {}
            caps = lane.get("caps") or {}
            if authorization.get("approved") is not True:
                raise ValueError(f"Remote qualification lane lacks explicit approval: {name}")
            required_caps = {
                "estimated_dollars_per_trial", "estimated_dollars_per_batch",
                "estimated_requests_per_trial", "max_requests_per_batch",
                "max_requests_per_run", "max_dollars_per_run",
                "pause_on_session_or_weekly_cap",
            }
            if not required_caps.issubset(caps):
                raise ValueError(f"Remote qualification lane lacks cap fields: {name}")
            if (
                int(caps["estimated_requests_per_trial"]) <= 0
                or int(caps["max_requests_per_batch"]) <= 0
                or int(caps["max_requests_per_run"]) <= 0
                or float(caps["max_dollars_per_run"]) != 0.0
                or float(caps["estimated_dollars_per_trial"]) != 0.0
                or float(caps["estimated_dollars_per_batch"]) != 0.0
                or caps["pause_on_session_or_weekly_cap"] is not True
            ):
                raise ValueError(f"Unsafe Ollama Pro qualification caps: {name}")
    payload["lanes"] = sorted(payload.get("lanes") or [], key=lambda lane: int(lane["rank"]))
    return payload


def _lane_state(lane: dict, plateau_trials: int, threshold: float) -> str:
    if lane.get("cap_exhausted"):
        return "cloud_cap_exhausted"
    trials = int(lane.get("trials", 0))
    pass_rate = float(lane.get("rolling_pass_rate", lane.get("pass_rate", 0.0)))
    if lane.get("formal_failed") and trials <= int(lane.get("last_formal_trial_count", trials)):
        return "sampling"
    top = lane.get("top_signatures") or []
    early_plateau = bool(top and int(top[0][1]) >= EARLY_STOP_FAILURES)
    if trials < plateau_trials and not early_plateau:
        return "sampling"
    if pass_rate >= threshold:
        return "threshold_met"
    top_signature = str(top[0][0]) if top else ""
    if top_signature and not top_signature.startswith(("brief/", "plan/")):
        return "non_planner_blocked"
    return "plateaued"


def _select_lane(
    config: dict,
    scoreboard: dict,
    fingerprint: str,
    explicitly_enabled: tuple[str, ...] = (),
) -> tuple[dict | None, dict]:
    threshold = float(config.get("pass_threshold", 0.8))
    plateau_trials = int(config.get("plateau_trials", MIN_RATCHET_TRIALS))
    entries = scoreboard.get("fingerprints", {}).get(fingerprint, {}).get("lanes", {})
    enabled_names = set(explicitly_enabled)
    known_names = {lane["name"] for lane in config["lanes"]}
    unknown = enabled_names - known_names
    if unknown:
        raise ValueError(f"Unknown qualification lane(s): {', '.join(sorted(unknown))}")

    for lane in config["lanes"]:
        name = lane["name"]
        state = _lane_state(entries.get(name, {}), plateau_trials, threshold)
        if state == "threshold_met":
            return None, {"status": "lane_threshold_met", "lane": name}
        if state == "non_planner_blocked":
            return None, {"status": "lane_escalation_blocked", "lane": name}
        if state == "cloud_cap_exhausted":
            return None, {"status": "cloud_cap_exhausted", "lane": name}
        if state == "sampling":
            if lane.get("remote") and name not in enabled_names:
                return None, {"status": "awaiting_explicit_enable", "next_lane": name}
            if not lane.get("enabled") and name not in enabled_names:
                continue
            return lane, {"status": "sampling", "lane": name}
    return None, {"status": "ladder_exhausted"}


def _record_lane_trial(
    lane: dict, evidence: IterationEvidence, result: dict, evidence_path: Path
) -> bool:
    iteration_ids = lane.setdefault("iteration_ids", [])
    trial_id = str(
        result.get("evidence_path")
        or result.get("qualification_trial_id")
        or evidence.iteration_id
    )
    if trial_id in iteration_ids:
        return False
    iteration_ids.append(trial_id)
    lane["trials"] = int(lane.get("trials", 0)) + 1
    lane["passes"] = int(lane.get("passes", 0)) + int(result.get("passed") is True)
    lane["pass_rate"] = round(lane["passes"] / lane["trials"], 4)
    lane["cap_exhausted"] = bool(
        lane.get("cap_exhausted") or result.get("remote_cap_exhausted")
    )
    lane.setdefault("evidence_paths", []).append(str(evidence_path))
    history = lane.setdefault("history", [])
    history.append({
        "passed": result.get("passed") is True,
        "failure_signature": result.get("failure_signature"),
        "evidence_path": str(evidence_path),
        "session_id": result.get("session_id"),
        "formal": result.get("formal") is True,
    })
    lane["history"] = history[-ROLLING_WINDOW:]
    lane["rolling_pass_rate"] = round(
        sum(int(item["passed"]) for item in lane["history"]) / len(lane["history"]), 4
    )
    if result.get("formal") is True:
        lane["formal_failed"] = result.get("passed") is not True
        lane["last_formal_trial_count"] = lane["trials"]

    stage_counts = lane.setdefault("stage_counts", {})
    for stage, stage_result in (result.get("stages") or {}).items():
        counts = stage_counts.setdefault(stage, {"trials": 0, "passes": 0})
        counts["trials"] += 1
        counts["passes"] += int(stage_result.get("status") in PASSING_STAGE_STATUSES)
    lane["stage_pass"] = {
        stage: round(counts["passes"] / counts["trials"], 4)
        for stage, counts in sorted(stage_counts.items())
    }

    if result.get("passed") is not True:
        signature = result.get("failure_signature") or "adapter/result/unsigned_failure"
        failures = lane.setdefault("signature_counts", {})
        failures[signature] = int(failures.get(signature, 0)) + 1
    lane["top_signatures"] = sorted(
        lane.get("signature_counts", {}).items(), key=lambda item: (-item[1], item[0])
    )
    return True


def _ratchet_verdict(scoreboard: dict, current: dict, stale: bool) -> str:
    tiers = current["tiers"]
    if stale:
        return "INDETERMINATE"
    if "fail" in tiers.values():
        return "REVERT"
    lanes = current["lanes"]
    if tiers != {"t0": "pass", "t1": "pass"} or not lanes:
        return "INDETERMINATE"
    candidate_lane, candidate = max(
        lanes.items(), key=lambda item: (item[1].get("pass_rate", 0.0), item[1].get("trials", 0))
    )
    if candidate.get("trials", 0) < MIN_RATCHET_TRIALS:
        return "INDETERMINATE"
    best = scoreboard.get("best")
    if best and candidate.get("pass_rate", 0.0) < best.get("pass_rate", 0.0):
        return "REVERT"
    scoreboard["best"] = {
        "fingerprint": current["fingerprint"],
        "lane": candidate_lane,
        "pass_rate": candidate["pass_rate"],
        "trials": candidate["trials"],
    }
    return "KEEP"


def _next_markdown(scoreboard: dict) -> str:
    current = scoreboard["current"]
    lanes = current["lanes"]
    lane_name = "none"
    lane = {}
    if lanes:
        lane_name, lane = max(
            lanes.items(), key=lambda item: (item[1].get("pass_rate", 0.0), item[1].get("trials", 0))
        )
    top = lane.get("top_signatures") or []
    top_signature = top[0][0] if top else "none"
    evidence_paths = lane.get("evidence_paths") or []
    evidence_path = evidence_paths[-1] if evidence_paths else "none"
    verdict = scoreboard["verdict"]
    scheduler = current.get("scheduler") or {}
    if scheduler.get("status") == "qualified":
        action = "Stop: serialized formal qualification passed; release record is ready for 13.6."
    elif scheduler.get("status") == "formal_failed":
        action = "Feed the formal failure into this lane and resume stochastic sampling."
    elif scheduler.get("status") == "stuck":
        action = "Pause GPU tiers and inspect STUCK.md; deterministic watch remains active."
    elif scheduler.get("status") == "budget_exhausted":
        action = "Pause GPU tiers and inspect BUDGET.md; deterministic watch remains active."
    elif scheduler.get("status") == "awaiting_explicit_enable":
        action = (
            "Cheaper planner lanes plateaued; explicitly enable approved lane "
            f"{scheduler.get('next_lane')} for this batch if its Pro caps remain available."
        )
    elif scheduler.get("status") == "lane_escalation_blocked":
        action = "Fix the non-planner failure before escalating the planner model lane."
    elif scheduler.get("status") == "cloud_cap_exhausted":
        action = "Pause the Ollama Pro lane; keep local deterministic work responsive."
    elif scheduler.get("status") == "lane_threshold_met":
        action = "Keep this lane winner; it is ready for the serialized formal trigger."
    elif scheduler.get("status") == "gpu_busy":
        gpu_checks = scheduler.get("gpu_checks") or []
        gpu_reason = (gpu_checks[-1].get("reason") if gpu_checks else None) or "local_comfyui_busy"
        action = f"Hold stochastic trials until the local ComfyUI guard clears: {gpu_reason}."
    elif scheduler.get("status") == "early_stopped":
        action = (
            "Stop sampling and fix the repeated signature: "
            f"{scheduler.get('early_stop_signature')}."
        )
    elif verdict == "REVERT" and "fail" in current["tiers"].values():
        action = "Fix or revert the deterministic Tier 0/1 defect before sampling."
    elif verdict == "REVERT":
        action = "Revert the source change or fix the regressed top failure signature."
    elif verdict == "KEEP":
        action = "Keep this fingerprint and continue toward the formal trigger."
    elif lane:
        remaining = max(0, MIN_RATCHET_TRIALS - lane.get("trials", 0))
        action = f"Collect {remaining} more fresh trial(s) for this fingerprint and lane."
    else:
        action = "Run a full iteration to collect a fresh real-lane trial."
    lines = [
        "# Ratchet NEXT",
        f"- Fingerprint: `{current['fingerprint']}`",
        f"- Verdict: `{verdict}`",
        f"- Tier 0: `{current['tiers']['t0']}`",
        f"- Tier 1: `{current['tiers']['t1']}`",
        f"- Lane: `{lane_name}`",
        f"- Pass rate: `{lane.get('pass_rate', 0.0)}` ({lane.get('passes', 0)}/{lane.get('trials', 0)})",
        f"- Top failure: `{top_signature}`",
        f"- Evidence: `{evidence_path}`",
        "",
        "## Next action",
        action,
    ]
    return "\n".join(lines) + "\n"


def _update_ratchet_files(
    scoreboard_path: Path, next_path: Path, root: Path, evidence: IterationEvidence
) -> None:
    scoreboard = _load_scoreboard(scoreboard_path)
    fingerprint = evidence.source_fingerprint_before
    fingerprint_entry = scoreboard["fingerprints"].setdefault(
        fingerprint, {"tiers": {}, "lanes": {}, "latest_iteration": None}
    )
    fingerprint_entry["tiers"] = _tier_statuses(evidence)
    fingerprint_entry["latest_iteration"] = evidence.iteration_id
    lane_batches = evidence.lane_results
    if not lane_batches and evidence.e2e_result is not None:
        lane_name = str(evidence.e2e_result.get("lane") or DEFAULT_LANE)
        lane_batches = {lane_name: (evidence.e2e_result,)}
    for lane_name, results in lane_batches.items():
        lane = fingerprint_entry["lanes"].setdefault(
            lane_name,
            {
                "trials": 0,
                "passes": 0,
                "pass_rate": 0.0,
                "stage_counts": {},
                "stage_pass": {},
                "signature_counts": {},
                "top_signatures": [],
                "iteration_ids": [],
                "evidence_paths": [],
            },
        )
        for result in results:
            evidence_path = Path(result.get("evidence_path") or (
                root / evidence.iteration_id / "v11-e2e.json"
            ))
            if _record_lane_trial(lane, evidence, result, evidence_path):
                fingerprint_history = fingerprint_entry.setdefault("history", [])
                fingerprint_history.append({
                    "lane": lane_name,
                    "passed": result.get("passed") is True,
                    "failure_signature": result.get("failure_signature"),
                    "evidence_path": str(evidence_path),
                    "session_id": result.get("session_id"),
                    "formal": result.get("formal") is True,
                })
                fingerprint_entry["history"] = fingerprint_history[-ROLLING_WINDOW:]
        winners = scoreboard.setdefault("lane_winners", {})
        winner = winners.get(lane_name)
        candidate_key = (
            lane["trials"] >= MIN_RATCHET_TRIALS,
            lane["pass_rate"],
            lane["trials"],
        )
        winner_key = (
            bool(winner and winner.get("trials", 0) >= MIN_RATCHET_TRIALS),
            float(winner.get("pass_rate", -1.0)) if winner else -1.0,
            int(winner.get("trials", 0)) if winner else 0,
        )
        if candidate_key > winner_key:
            winners[lane_name] = {
                "fingerprint": fingerprint,
                "pass_rate": lane["pass_rate"],
                "trials": lane["trials"],
            }
    fingerprint_entry["scheduler"] = evidence.scheduler
    current = {
        "fingerprint": fingerprint,
        "tiers": fingerprint_entry["tiers"],
        "lanes": fingerprint_entry["lanes"],
        "scheduler": fingerprint_entry["scheduler"],
    }
    scoreboard["current"] = current
    scoreboard["verdict"] = _ratchet_verdict(scoreboard, current, evidence.stale)
    scoreboard["updated_at_epoch"] = evidence.finished_at_epoch
    _atomic_write(scoreboard_path, json.dumps(scoreboard, indent=2, sort_keys=True) + "\n")
    _atomic_write(next_path, _next_markdown(scoreboard))


class EvidenceStore:
    def __init__(self, root: Path):
        self.root = root
        self.events = root / "events.jsonl"
        self.latest = root / "latest.json"
        self.scoreboard = root / "scoreboard.json"
        self.next = root / "NEXT.md"

    def previous(self) -> dict | None:
        try:
            return json.loads(self.latest.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def write(self, evidence: IterationEvidence) -> Path:
        payload = evidence.model_dump(mode="json")
        canonical = _canonical_json(payload)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(canonical + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        iteration_dir = self.root / evidence.iteration_id
        json_path = iteration_dir / "summary.json"
        _atomic_write(json_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        lines = [
            f"# Qualification {evidence.iteration_id}",
            f"- Verdict: {'PASS' if evidence.passed else 'FAIL'}",
            f"- Mode: `{evidence.mode}`",
            f"- Source: `{evidence.source_fingerprint_before}`",
            f"- Stale: `{str(evidence.stale).lower()}`",
            f"- Duration: `{evidence.duration_seconds}s`",
            "", "## Commands",
        ]
        lines.extend(
            f"- `{command.name}`: {'PASS' if command.passed else 'FAIL'} "
            f"({command.duration_seconds}s, exit={command.returncode}, timeout={command.timed_out})"
            for command in evidence.commands
        )
        if evidence.mock_e2e_result:
            lines.extend([
                "", "## Deterministic Mock V11 E2E",
                f"- Session: `{evidence.mock_e2e_result.get('session_id')}`",
                f"- Verdict: `{'PASS' if evidence.mock_e2e_result.get('passed') else 'FAIL'}`",
            ])
        if evidence.e2e_result:
            lines.extend([
                "", "## Fresh V11 E2E",
                f"- Session: `{evidence.e2e_result.get('session_id')}`",
                f"- Verdict: `{'PASS' if evidence.e2e_result.get('passed') else 'FAIL'}`",
            ])
        if evidence.scheduler:
            lines.extend([
                "", "## Tier 2 Scheduler",
                f"- Status: `{evidence.scheduler.get('status')}`",
                f"- Lane: `{evidence.scheduler.get('lane')}`",
                f"- Workers: `{evidence.scheduler.get('workers')}`",
                f"- Trials: `{evidence.scheduler.get('total_trials')}` "
                f"({evidence.scheduler.get('new_trials')} new)",
                f"- VRAM: `{json.dumps(evidence.scheduler.get('vram') or {}, sort_keys=True)}`",
            ])
        _atomic_write(iteration_dir / "report.md", "\n".join(lines) + "\n")
        _atomic_write(self.latest, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        _update_ratchet_files(self.scoreboard, self.next, self.root, evidence)
        if evidence.qualified:
            formal = evidence.scheduler.get("formal") or {}
            _atomic_write(self.root / "QUALIFIED.md", "\n".join([
                "# QUALIFIED", f"- Fingerprint: `{evidence.source_fingerprint_before}`",
                f"- Lane: `{formal.get('lane')}`", f"- Session: `{formal.get('session_id')}`",
                f"- Evidence: `{formal.get('evidence_path')}`",
                "- Git action: `none` (release record ready for explicit 13.6 staging)", "",
            ]))
        elif evidence.stop_condition == "STUCK":
            _atomic_write(self.root / "STUCK.md", "\n".join([
                "# STUCK", f"- Fingerprint: `{evidence.source_fingerprint_before}`",
                f"- Lane: `{evidence.scheduler.get('lane')}`",
                f"- Signature: `{evidence.scheduler.get('failure_signature')}`",
                f"- Evidence: `{json.dumps(evidence.scheduler.get('evidence_paths') or [])}`", "",
            ]))
        elif evidence.stop_condition == "BUDGET":
            _atomic_write(self.root / "BUDGET.md", "\n".join([
                "# BUDGET", f"- Fingerprint: `{evidence.source_fingerprint_before}`",
                f"- Reason: `{evidence.scheduler.get('reason') or evidence.scheduler.get('status')}`",
                "- GPU tiers paused; deterministic watch remains responsive.", "",
            ]))
        return json_path


def _regression_delta(
    previous: dict | None,
    commands: list[CommandEvidence],
    mock_e2e: dict | None,
    e2e: dict | None,
) -> dict:
    current_failures = sorted(command.name for command in commands if not command.passed)
    if mock_e2e and not mock_e2e.get("passed"):
        current_failures.append("mock-v11-e2e-evidence")
    if e2e and not e2e.get("passed"):
        current_failures.append("fresh-v11-e2e-evidence")
    previous_failures = []
    if previous:
        previous_failures = sorted(
            command["name"] for command in previous.get("commands", []) if not command.get("passed")
        )
        prior_mock = previous.get("mock_e2e_result")
        if prior_mock and not prior_mock.get("passed"):
            previous_failures.append("mock-v11-e2e-evidence")
        prior_e2e = previous.get("e2e_result")
        if prior_e2e and not prior_e2e.get("passed"):
            previous_failures.append("fresh-v11-e2e-evidence")
    return {
        "new_failures": sorted(set(current_failures) - set(previous_failures)),
        "resolved_failures": sorted(set(previous_failures) - set(current_failures)),
        "current_failures": sorted(current_failures),
    }


def _read_result(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "passed": False,
            "failure_signature": "adapter/result/invalid_json",
            "error": f"invalid E2E JSON: {exc}",
        }


def _measure_vram_headroom() -> dict:
    measured = time.time()
    argv = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,memory.free",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            argv, cwd=ROOT, env=_sanitized_environment(), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=5,
            check=False, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "available": False, "measured_at_epoch": measured,
            "reason": type(exc).__name__,
        }
    if completed.returncode != 0 or not completed.stdout.strip():
        return {
            "available": False, "measured_at_epoch": measured,
            "reason": "nvidia_smi_failed",
        }
    try:
        name, total, used, free = [part.strip() for part in completed.stdout.splitlines()[0].split(",")]
        return {
            "available": True, "measured_at_epoch": measured, "gpu": name,
            "total_mib": int(total), "used_mib": int(used), "free_mib": int(free),
        }
    except (TypeError, ValueError):
        return {
            "available": False, "measured_at_epoch": measured,
            "reason": "unparseable_nvidia_smi",
        }


def _effective_workers(requested: int, vram: dict) -> int:
    requested = max(1, requested)
    if requested <= DEFAULT_TRIAL_WORKERS:
        return requested
    if not vram.get("available") or int(vram.get("free_mib", 0)) < K3_MIN_FREE_VRAM_MIB:
        return DEFAULT_TRIAL_WORKERS
    return min(requested, 3)


def _comfyui_gpu_state(timeout: float = 2.0) -> dict:
    base_url = os.getenv("COMFYUI_URL", "http://localhost:8188").rstrip("/")
    host = (urlparse(base_url).hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return {
            "status": "non_local_rejected", "busy": True,
            "reason": "canon_comfyui_must_be_local",
        }
    try:
        with urlopen(f"{base_url}/queue", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {
            "status": "unavailable", "busy": True,
            "reason": f"comfyui_unavailable:{type(exc).__name__}",
        }
    serialized = json.dumps(payload, sort_keys=True).lower()
    model_download = any(token in serialized for token in (
        "downloadandload", "download_model", "model download", "model_manager",
    ))
    return {
        "status": "model_download" if model_download else "ready",
        "busy": model_download,
        "queue_running": len(payload.get("queue_running") or []),
        "queue_pending": len(payload.get("queue_pending") or []),
    }


def _trial_summary(result: dict | None, path: Path, lane: str, index: int) -> dict:
    result = result or {
        "passed": False,
        "failure_signature": "adapter/result/missing",
        "stages": {},
    }
    diagnostic = _canonical_json({
        "failure_signature": result.get("failure_signature"),
        "failure_signatures": result.get("failure_signatures"),
        "error": result.get("error"),
        "exception": result.get("exception"),
    }).lower()
    remote_cap_exhausted = any(token in diagnostic for token in (
        "weekly_limit", "session_limit", "usage_limit", "quota_exhausted",
        "insufficient_quota", "pro_cap_exhausted",
    ))
    return {
        "lane": lane,
        "trial_index": index,
        "evidence_path": str(path),
        "passed": result.get("passed") is True,
        "session_id": result.get("session_id"),
        "failure_signature": result.get("failure_signature"),
        "remote_cap_exhausted": remote_cap_exhausted,
        "stages": {
            stage: {"status": value.get("status")}
            for stage, value in (result.get("stages") or {}).items()
        },
    }


def _run_real_trial(
    iteration_dir: Path,
    lane: str,
    index: int,
    timeout: float,
    lane_env: dict[str, str] | None = None,
) -> tuple[CommandEvidence, dict]:
    result_path = iteration_dir / "trials" / lane / f"trial-{index:02d}.json"
    child_env = dict(REAL_TRIAL_ENV)
    child_env.update(lane_env or {})
    command = run_command(
        f"fresh-v11-e2e:{lane}:{index}",
        [sys.executable, "tools/v11_e2e_adapter.py", "--result", str(result_path)],
        timeout,
        env_overrides=child_env,
    )
    return command, _trial_summary(_read_result(result_path), result_path, lane, index)


def _first_three_identical_failures(results: list[dict]) -> str | None:
    if len(results) < EARLY_STOP_FAILURES:
        return None
    first = results[:EARLY_STOP_FAILURES]
    signatures = [result.get("failure_signature") for result in first]
    if all(result.get("passed") is not True for result in first) and signatures[0] and len(set(signatures)) == 1:
        return str(signatures[0])
    return None


def _prior_lane_results(store: EvidenceStore, fingerprint: str, lane: str) -> list[dict]:
    scoreboard = _load_scoreboard(store.scoreboard)
    lane_entry = (
        scoreboard.get("fingerprints", {}).get(fingerprint, {})
        .get("lanes", {}).get(lane, {})
    )
    history = lane_entry.get("history") or []
    if history:
        return [
            {**item, "lane": lane, "trial_index": index}
            for index, item in enumerate(history, start=1)
        ]
    results = []
    for index, value in enumerate(lane_entry.get("evidence_paths") or [], start=1):
        path = Path(value)
        results.append(_trial_summary(_read_result(path), path, lane, index))
    return results


def _run_stochastic_trials(
    store: EvidenceStore,
    iteration_dir: Path,
    fingerprint: str,
    timeout: float,
    *,
    lane: str = DEFAULT_LANE,
    lane_env: dict[str, str] | None = None,
    remote: bool = False,
    caps: dict | None = None,
    requested_workers: int = DEFAULT_TRIAL_WORKERS,
    trial_limit: int = MIN_RATCHET_TRIALS,
) -> tuple[list[CommandEvidence], tuple[dict, ...], dict]:
    vram = _measure_vram_headroom()
    workers = _effective_workers(requested_workers, vram)
    caps = caps or {}
    estimated_requests = max(1, int(caps.get("estimated_requests_per_trial", 1)))
    request_limit = min(
        int(caps.get("max_requests_per_batch", trial_limit * estimated_requests)),
        int(caps.get("max_requests_per_run", trial_limit * estimated_requests)),
    )
    run_trial_limit = min(trial_limit, request_limit // estimated_requests) if remote else trial_limit
    prior = _prior_lane_results(store, fingerprint, lane)[:trial_limit]
    history = list(prior)
    new_results: list[dict] = []
    commands: list[CommandEvidence] = []
    gpu_checks: list[dict] = []
    stopped_signature = _first_three_identical_failures(history)
    cap_exhausted = bool(remote and run_trial_limit <= 0)

    while (
        len(history) < trial_limit
        and len(new_results) < run_trial_limit
        and stopped_signature is None
        and not cap_exhausted
    ):
        before_early_decision = len(history) < EARLY_STOP_FAILURES
        batch_limit = EARLY_STOP_FAILURES - len(history) if before_early_decision else trial_limit - len(history)
        batch_size = min(
            workers,
            trial_limit - len(history),
            run_trial_limit - len(new_results),
            batch_limit,
        )
        gpu_state = _comfyui_gpu_state()
        gpu_checks.append(gpu_state)
        if gpu_state.get("busy"):
            break
        start_index = len(history) + 1
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = [
                executor.submit(
                    _run_real_trial,
                    iteration_dir,
                    lane,
                    start_index + offset,
                    timeout,
                    lane_env,
                )
                for offset in range(batch_size)
            ]
            batch = [future.result() for future in futures]
        commands.extend(command for command, _result in batch)
        summaries = [result for _command, result in batch]
        new_results.extend(summaries)
        history.extend(summaries)
        cap_exhausted = bool(
            remote and any(result.get("remote_cap_exhausted") for result in summaries)
        )
        stopped_signature = _first_three_identical_failures(history)

    gpu_busy = bool(gpu_checks and gpu_checks[-1].get("busy"))
    if remote and len(new_results) >= run_trial_limit and len(history) < trial_limit:
        cap_exhausted = True
    status = (
        "gpu_busy" if gpu_busy else
        "cloud_cap_exhausted" if cap_exhausted else
        "early_stopped" if stopped_signature else
        "complete" if len(history) >= trial_limit else
        "incomplete"
    )
    scheduler = {
        "schema_version": "qualification-scheduler/v1",
        "status": status,
        "lane": lane,
        "lane_env": dict(sorted((lane_env or {}).items())),
        "remote": remote,
        "requested_workers": requested_workers,
        "workers": workers,
        "trial_limit": trial_limit,
        "run_trial_limit": run_trial_limit,
        "request_cap": request_limit if remote else None,
        "estimated_requests_per_trial": estimated_requests if remote else None,
        "estimated_dollars_per_trial": caps.get("estimated_dollars_per_trial") if remote else None,
        "estimated_dollars_per_batch": caps.get("estimated_dollars_per_batch") if remote else None,
        "max_dollars_per_run": caps.get("max_dollars_per_run") if remote else None,
        "prior_trials": len(prior),
        "new_trials": len(new_results),
        "total_trials": len(history),
        "early_stop_signature": stopped_signature,
        "gpu_checks": gpu_checks,
        "vram": vram,
        "ollama_num_parallel": 2,
        "k3_attempted": requested_workers >= 3 and workers >= 3,
    }
    return commands, tuple(new_results), scheduler


def _lane_config(config: dict, name: str) -> dict:
    return next(lane for lane in config["lanes"] if lane["name"] == name)


def _formal_ready(lane_entry: dict, new_results: tuple[dict, ...], threshold: float) -> bool:
    history = list(lane_entry.get("history") or []) + list(new_results)
    window = history[-ROLLING_WINDOW:]
    return (
        len(window) >= MIN_RATCHET_TRIALS
        and sum(int(item.get("passed") is True) for item in window) / len(window) >= threshold
    )


def _stuck_state(scoreboard: dict, fingerprint: str) -> dict | None:
    fingerprint_entry = scoreboard.get("fingerprints", {}).get(fingerprint, {})
    histories = [("multiple", fingerprint_entry.get("history") or [])]
    histories.extend(
        (lane_name, lane.get("history") or [])
        for lane_name, lane in fingerprint_entry.get("lanes", {}).items()
    )
    for lane_name, history in histories:
        recent = history[-STUCK_FAILURES:]
        signatures = [item.get("failure_signature") for item in recent]
        if (
            len(recent) == STUCK_FAILURES
            and signatures[0]
            and len(set(signatures)) == 1
            and all(item.get("passed") is not True for item in recent)
        ):
            return {
                "status": "stuck",
                "lane": lane_name,
                "failure_signature": signatures[0],
                "evidence_paths": [item.get("evidence_path") for item in recent],
            }
    return None


def _run_formal_trial(
    iteration_dir: Path,
    lane: str,
    timeout: float,
    lane_env: dict[str, str],
) -> tuple[CommandEvidence, dict]:
    result_path = iteration_dir / "formal-v11-e2e.json"
    child_env = dict(REAL_TRIAL_ENV)
    child_env.update(lane_env)
    command = run_command(
        f"formal-v11-e2e:{lane}",
        [sys.executable, "tools/v11_e2e_adapter.py", "--result", str(result_path)],
        timeout,
        env_overrides=child_env,
    )
    summary = _trial_summary(_read_result(result_path), result_path, lane, 0)
    summary["formal"] = True
    return command, summary


def run_iteration(
    store: EvidenceStore,
    mode: str,
    timeout: float,
    changed_files: tuple[str, ...],
    trial_workers: int = DEFAULT_TRIAL_WORKERS,
    trial_limit: int = MIN_RATCHET_TRIALS,
    lanes_config: Path = DEFAULT_LANES_CONFIG,
    enabled_lanes: tuple[str, ...] = (),
    budget_deadline: float | None = None,
) -> IterationEvidence:
    started = time.time()
    fingerprint_before = source_fingerprint()
    iteration_id = f"{_safe_timestamp()}-{fingerprint_before[:10]}"
    iteration_dir = store.root / iteration_id
    e2e_path = iteration_dir / "v11-e2e.json"
    mock_e2e_path = iteration_dir / "mock-v11-e2e.json"
    commands: list[CommandEvidence] = []
    print(
        f"[qualification] START iteration={iteration_id} mode={mode} "
        f"source={fingerprint_before[:12]}",
        flush=True,
    )
    for name, argv in command_plan(mode, e2e_path):
        print(f"[qualification] START command={name}", flush=True)
        evidence = run_command(
            name,
            argv,
            timeout,
            env_overrides=MOCK_E2E_ENV if name == "mock-v11-e2e" else None,
        )
        commands.append(evidence)
        print(
            f"[qualification] {'PASS' if evidence.passed else 'FAIL'} "
            f"command={name} duration={evidence.duration_seconds}s "
            f"exit={evidence.returncode} timeout={evidence.timed_out}",
            flush=True,
        )
        if not evidence.passed:
            break

    prefix_passed = bool(commands) and all(command.passed for command in commands)
    mock_e2e_result = _read_result(mock_e2e_path)
    e2e_result = _read_result(e2e_path)
    lane_results: dict[str, tuple[dict, ...]] = {}
    scheduler: dict = {}
    qualified = False
    stop_condition: str | None = None
    if (
        mode == "full"
        and prefix_passed
        and mock_e2e_result
        and mock_e2e_result.get("passed") is True
    ):
        lane_config = _load_lanes_config(lanes_config)
        scoreboard = _load_scoreboard(store.scoreboard)
        stuck = _stuck_state(scoreboard, fingerprint_before)
        trial_commands: list[CommandEvidence] = []
        summaries: tuple[dict, ...] = ()
        selected_lane: dict | None = None
        selection: dict = {}
        if budget_deadline is not None and time.time() >= budget_deadline:
            scheduler = {
                "schema_version": "qualification-scheduler/v1",
                "status": "budget_exhausted",
                "reason": "wall_clock_budget",
                "new_trials": 0,
                "total_trials": 0,
            }
            stop_condition = "BUDGET"
        elif stuck:
            scheduler = {"schema_version": "qualification-scheduler/v1", **stuck, "new_trials": 0}
            stop_condition = "STUCK"
        else:
            selected_lane, selection = _select_lane(
                lane_config, scoreboard, fingerprint_before, enabled_lanes
            )
            if selected_lane is None:
                scheduler = {
                    "schema_version": "qualification-scheduler/v1",
                    **selection,
                    "new_trials": 0,
                    "total_trials": 0,
                }
            else:
                lane_entry = (
                    scoreboard.get("fingerprints", {}).get(fingerprint_before, {})
                    .get("lanes", {}).get(selected_lane["name"], {})
                )
                sample_target = trial_limit
                if lane_entry.get("formal_failed"):
                    sample_target = max(trial_limit, int(lane_entry.get("trials", 0)) + 1)
                trial_commands, summaries, scheduler = _run_stochastic_trials(
                    store,
                    iteration_dir,
                    fingerprint_before,
                    timeout,
                    lane=selected_lane["name"],
                    lane_env=selected_lane.get("env") or {},
                    remote=bool(selected_lane.get("remote")),
                    caps=selected_lane.get("caps") or {},
                    requested_workers=trial_workers,
                    trial_limit=sample_target,
                )

            selected_name = selected_lane["name"] if selected_lane else selection.get("lane")
            if selected_name and summaries:
                lane_results[selected_name] = summaries
            e2e_result = summaries[-1] if summaries else None

            formal_lane: dict | None = None
            if scheduler.get("status") == "lane_threshold_met" and selected_name:
                formal_lane = _lane_config(lane_config, selected_name)
            elif selected_lane and scheduler.get("status") == "complete":
                lane_entry = (
                    scoreboard.get("fingerprints", {}).get(fingerprint_before, {})
                    .get("lanes", {}).get(selected_lane["name"], {})
                )
                if _formal_ready(lane_entry, summaries, float(lane_config["pass_threshold"])):
                    formal_lane = selected_lane

            if formal_lane:
                formal_gpu_check = _comfyui_gpu_state()
                scheduler["formal_gpu_check"] = formal_gpu_check
                if formal_gpu_check.get("busy"):
                    scheduler["status"] = "gpu_busy"
                else:
                    formal_command, formal_summary = _run_formal_trial(
                        iteration_dir,
                        formal_lane["name"],
                        timeout,
                        formal_lane.get("env") or {},
                    )
                    trial_commands.append(formal_command)
                    commands.append(formal_command)
                    lane_results[formal_lane["name"]] = (
                        lane_results.get(formal_lane["name"], ()) + (formal_summary,)
                    )
                    e2e_result = formal_summary
                    qualified = formal_summary.get("passed") is True
                    scheduler["status"] = "qualified" if qualified else "formal_failed"
                    scheduler["formal"] = {
                        "lane": formal_lane["name"],
                        "session_id": formal_summary.get("session_id"),
                        "evidence_path": formal_summary.get("evidence_path"),
                        "passed": qualified,
                    }
                    if qualified:
                        stop_condition = "QUALIFIED"

            if scheduler.get("status") == "cloud_cap_exhausted":
                stop_condition = "BUDGET"

        commands.extend(command for command in trial_commands if command not in commands)
        for command in trial_commands:
            print(
                f"[qualification] {'PASS' if command.passed else 'FAIL'} "
                f"command={command.name} duration={command.duration_seconds}s "
                f"exit={command.returncode} timeout={command.timed_out}",
                flush=True,
            )
        print(
            f"[qualification] SCHEDULER status={scheduler.get('status')} "
            f"workers={scheduler.get('workers')} new={scheduler.get('new_trials')} "
            f"total={scheduler.get('total_trials')}",
            flush=True,
        )

    fingerprint_after = source_fingerprint()
    stale = fingerprint_before != fingerprint_after
    previous = store.previous()
    if mode == "tests-only":
        passed = not stale and prefix_passed
    elif mode == "e2e-only":
        passed = not stale and prefix_passed and bool(e2e_result and e2e_result.get("passed"))
    else:
        passed = (
            not stale
            and prefix_passed
            and scheduler.get("status") in {
                "complete", "early_stopped", "gpu_busy", "lane_threshold_met",
                "lane_escalation_blocked", "awaiting_explicit_enable",
                "cloud_cap_exhausted", "ladder_exhausted", "formal_failed",
                "qualified", "stuck", "budget_exhausted",
            }
        )
    finished = time.time()
    result = IterationEvidence(
        iteration_id=iteration_id,
        mode=mode,
        started_at_epoch=started,
        finished_at_epoch=finished,
        duration_seconds=round(finished - started, 3),
        source_fingerprint_before=fingerprint_before,
        source_fingerprint_after=fingerprint_after,
        stale=stale,
        changed_files=changed_files,
        commands=tuple(commands),
        mock_e2e_result=mock_e2e_result,
        e2e_result=e2e_result,
        lane_results=lane_results,
        scheduler=scheduler,
        qualified=qualified,
        stop_condition=stop_condition,
        regression_delta=_regression_delta(
            previous, commands, mock_e2e_result, e2e_result
        ),
        passed=passed,
    )
    store.write(result)
    return result


def _agent_turn_active(marker: Path) -> bool:
    value = os.getenv("KIRO_AGENT_ACTIVE", "").strip().lower()
    return marker.exists() or value in {"1", "true", "yes", "on"}


def _run_idle_f0(
    baseline: str,
    *,
    corpus_path: Path,
    log_path: Path,
    agent_active_file: Path,
) -> bool:
    if _agent_turn_active(agent_active_file):
        return False
    gpu_state = _comfyui_gpu_state()
    if gpu_state.get("status") == "model_download":
        return False
    from tools.flywheel_corpus import extract_corpus

    stop_requested = lambda: (
        source_fingerprint() != baseline or _agent_turn_active(agent_active_file)
    )
    result = extract_corpus(
        root=ROOT,
        corpus_path=corpus_path,
        log_path=log_path,
        max_records=25,
        stop_requested=stop_requested,
    )
    if result.get("status") != "complete" or stop_requested():
        return False

    from tools.qualification_briefing import run_briefing

    briefing = run_briefing(
        root=ROOT,
        log_path=log_path,
        stop_requested=stop_requested,
    )
    return briefing.get("status") in {
        "complete", "complete_with_model_warning", "skipped", "no_evidence",
    }


def _scheduler_waits_for_comfyui(evidence: IterationEvidence) -> bool:
    return evidence.scheduler.get("status") == "gpu_busy"


def _wait_for_comfyui_wake(
    baseline: str,
    debounce_seconds: float,
    recheck_seconds: float,
    *,
    budget_deadline: float | None = None,
) -> str:
    next_recheck = time.monotonic() + recheck_seconds
    print(
        f"[qualification] HOLD comfyui recheck_seconds={recheck_seconds:g}",
        flush=True,
    )
    while True:
        time.sleep(min(0.5, max(0.1, debounce_seconds)))
        current = source_fingerprint()
        if current != baseline:
            stable_since = time.monotonic()
            last = current
            while time.monotonic() - stable_since < debounce_seconds:
                time.sleep(min(0.5, max(0.1, debounce_seconds / 2.0)))
                current = source_fingerprint()
                if current != last:
                    last = current
                    stable_since = time.monotonic()
            return last
        if budget_deadline is not None and time.time() >= budget_deadline:
            print("[qualification] WAKE reason=budget_deadline", flush=True)
            return baseline
        if time.monotonic() < next_recheck:
            continue
        state = _comfyui_gpu_state()
        print(
            f"[qualification] RECHECK comfyui status={state.get('status')} "
            f"busy={state.get('busy')} reason={state.get('reason')}",
            flush=True,
        )
        if not state.get("busy"):
            print("[qualification] WAKE reason=comfyui_ready", flush=True)
            return baseline
        next_recheck = time.monotonic() + recheck_seconds


def _wait_for_stable_change(
    baseline: str,
    debounce_seconds: float,
    *,
    idle_seconds: float = DEFAULT_FLYWHEEL_IDLE_SECONDS,
    idle_callback: Callable[[], bool] | None = None,
) -> str:
    quiet_since = time.monotonic() if idle_callback else 0.0
    idle_ran = False
    next_idle_check = quiet_since + idle_seconds
    while True:
        time.sleep(min(0.5, max(0.1, debounce_seconds)))
        current = source_fingerprint()
        if current == baseline:
            if idle_callback and not idle_ran and time.monotonic() >= next_idle_check:
                idle_ran = bool(idle_callback())
                if not idle_ran:
                    next_idle_check = time.monotonic() + 5.0
            continue
        stable_since = time.monotonic()
        last = current
        while time.monotonic() - stable_since < debounce_seconds:
            time.sleep(min(0.5, max(0.1, debounce_seconds / 2.0)))
            current = source_fingerprint()
            if current != last:
                last = current
                stable_since = time.monotonic()
        return last


def run_loop(args: argparse.Namespace) -> int:
    mode = "tests-only" if args.tests_only else "e2e-only" if args.e2e_only else "full"
    store = EvidenceStore(args.output_root.resolve())
    changed = tuple(args.changed_files or ())
    count = 0
    baseline = source_fingerprint()
    budget_deadline = time.time() + args.budget_hours * 3600.0
    pending = True
    waiting_for_comfyui = False
    last_result: IterationEvidence | None = None
    while pending or args.watch:
        if pending:
            last_result = run_iteration(
                store, mode, args.timeout, changed,
                trial_workers=args.trial_workers,
                trial_limit=args.trials_per_lane,
                lanes_config=args.lanes_config,
                enabled_lanes=tuple(args.enable_lane or ()),
                budget_deadline=budget_deadline,
            )
            count += 1
            print(_canonical_json({
                "iteration_id": last_result.iteration_id,
                "passed": last_result.passed,
                "stale": last_result.stale,
                "source": last_result.source_fingerprint_before,
            }), flush=True)
            baseline = last_result.source_fingerprint_after
            pending = last_result.stale
            waiting_for_comfyui = bool(
                args.watch
                and not last_result.stale
                and _scheduler_waits_for_comfyui(last_result)
            )
            changed = ()
            if last_result.qualified:
                break
            if args.max_iterations and count >= args.max_iterations:
                break
            if not args.watch and not pending:
                break
            continue
        if waiting_for_comfyui:
            baseline = _wait_for_comfyui_wake(
                baseline,
                args.debounce_seconds,
                args.readiness_recheck_seconds,
                budget_deadline=budget_deadline,
            )
            pending = True
            waiting_for_comfyui = False
            changed = ()
            continue
        new_fingerprint = _wait_for_stable_change(
            baseline,
            args.debounce_seconds,
            idle_seconds=args.flywheel_idle_seconds,
            idle_callback=lambda: _run_idle_f0(
                baseline,
                corpus_path=args.flywheel_corpus.resolve(),
                log_path=args.flywheel_log.resolve(),
                agent_active_file=args.agent_active_file.resolve(),
            ),
        )
        pending = new_fingerprint != baseline
    return 0 if last_result and last_result.passed else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--watch", action="store_true")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--tests-only", action="store_true")
    scope.add_argument("--e2e-only", action="store_true")
    parser.add_argument("--changed-files", nargs="*")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--debounce-seconds", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--budget-hours", type=float, default=DEFAULT_BUDGET_HOURS)
    parser.add_argument("--max-iterations", type=int, default=0)
    parser.add_argument("--trial-workers", type=int, default=DEFAULT_TRIAL_WORKERS)
    parser.add_argument("--trials-per-lane", type=int, default=MIN_RATCHET_TRIALS)
    parser.add_argument("--lanes-config", type=Path, default=DEFAULT_LANES_CONFIG)
    parser.add_argument("--flywheel-corpus", type=Path, default=DEFAULT_FLYWHEEL_CORPUS)
    parser.add_argument("--flywheel-log", type=Path, default=DEFAULT_FLYWHEEL_LOG)
    parser.add_argument("--agent-active-file", type=Path, default=DEFAULT_AGENT_ACTIVE_FILE)
    parser.add_argument(
        "--flywheel-idle-seconds", type=float, default=DEFAULT_FLYWHEEL_IDLE_SECONDS,
    )
    parser.add_argument(
        "--readiness-recheck-seconds",
        type=float,
        default=DEFAULT_READINESS_RECHECK_SECONDS,
        help="Seconds between ComfyUI readiness checks while stochastic tiers are held.",
    )
    parser.add_argument(
        "--enable-lane", action="append", default=[],
        help="Explicitly enable a disabled approved lane for this run (repeatable).",
    )
    args = parser.parse_args(argv)
    if not args.once and not args.watch:
        args.once = True
    if (
        args.debounce_seconds < 0
        or args.timeout <= 0
        or args.budget_hours <= 0
        or args.flywheel_idle_seconds < 0
        or args.readiness_recheck_seconds <= 0
        or args.max_iterations < 0
        or args.trial_workers <= 0
        or args.trials_per_lane <= 0
    ):
        parser.error(
            "debounce/max-iterations/flywheel-idle-seconds must be non-negative; "
            "timeout, budget-hours, readiness-recheck-seconds, trial-workers, and "
            "trials-per-lane must be positive"
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    lock = args.output_root.resolve() / ".qualification.lock"
    try:
        with ProcessLock(lock):
            return run_loop(args)
    except KeyboardInterrupt:
        print("qualification interrupted", file=sys.stderr)
        return 130
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
