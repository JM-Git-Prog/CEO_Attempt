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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "output" / "qualification"
INCLUDE_ROOTS = ("src", "tests", "tools", ".kiro/specs/llm-driven-upbge-runtime")
INCLUDE_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".md", ".toml"}
EXCLUDED_PARTS = {".git", ".kirograph", "output", "__pycache__", ".pytest_cache", ".hypothesis"}
SAFE_ENV = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "PYTHONUTF8",
    "PYTHONIOENCODING", "OLLAMA_HOST", "COMFYUI_URL", "NO_PROXY",
}


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
    e2e_result: dict | None
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


def _sanitized_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV}
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def run_command(name: str, argv: list[str], timeout: float) -> CommandEvidence:
    started = time.time()
    returncode: int | None = None
    timed_out = False
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            env=_sanitized_environment(),
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


def _focused_tests() -> list[str]:
    requested = [
        "tests/test_composition_sidecar.py", "tests/test_floor_plan_builder.py",
        "tests/test_world_contract.py", "tests/test_relationship_solver.py",
        "tests/test_compiler_manifest.py", "tests/test_upbge_capability.py",
        "tests/test_upbge_compiler.py", "tests/test_export_adapters.py",
        "tests/test_structural_parity.py", "tests/test_runtime_smoke.py",
        "tests/test_glb_reload.py", "tests/test_v11_pipeline.py",
        "tests/test_v11_web.py", "tests/test_qa_evidence.py",
    ]
    return [value for value in requested if (ROOT / value).exists()]


def command_plan(mode: str, e2e_result_path: Path) -> list[tuple[str, list[str]]]:
    python = sys.executable
    commands: list[tuple[str, list[str]]] = []
    if mode != "e2e-only":
        commands.extend([
            ("compileall", [python, "-m", "compileall", "-q", "src", "tools"]),
            ("node-check", ["node", "--check", "src/web/static/app.js"]),
            ("focused-tests", [python, "-m", "pytest", *_focused_tests(), "-q"]),
            ("full-tests", [python, "-m", "pytest", "tests", "-q"]),
        ])
    if mode != "tests-only":
        commands.append((
            "fresh-v11-e2e",
            [python, "tools/v11_e2e_adapter.py", "--result", str(e2e_result_path)],
        ))
    return commands


class EvidenceStore:
    def __init__(self, root: Path):
        self.root = root
        self.events = root / "events.jsonl"
        self.latest = root / "latest.json"

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
        if evidence.e2e_result:
            lines.extend([
                "", "## Fresh V11 E2E",
                f"- Session: `{evidence.e2e_result.get('session_id')}`",
                f"- Verdict: `{'PASS' if evidence.e2e_result.get('passed') else 'FAIL'}`",
            ])
        _atomic_write(iteration_dir / "report.md", "\n".join(lines) + "\n")
        _atomic_write(self.latest, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return json_path


def _regression_delta(previous: dict | None, commands: list[CommandEvidence], e2e: dict | None) -> dict:
    current_failures = sorted(command.name for command in commands if not command.passed)
    if e2e and not e2e.get("passed"):
        current_failures.append("fresh-v11-e2e-evidence")
    previous_failures = []
    if previous:
        previous_failures = sorted(
            command["name"] for command in previous.get("commands", []) if not command.get("passed")
        )
        prior_e2e = previous.get("e2e_result")
        if prior_e2e and not prior_e2e.get("passed"):
            previous_failures.append("fresh-v11-e2e-evidence")
    return {
        "new_failures": sorted(set(current_failures) - set(previous_failures)),
        "resolved_failures": sorted(set(previous_failures) - set(current_failures)),
        "current_failures": sorted(current_failures),
    }


def run_iteration(
    store: EvidenceStore,
    mode: str,
    timeout: float,
    changed_files: tuple[str, ...],
) -> IterationEvidence:
    started = time.time()
    fingerprint_before = source_fingerprint()
    iteration_id = f"{_safe_timestamp()}-{fingerprint_before[:10]}"
    iteration_dir = store.root / iteration_id
    e2e_path = iteration_dir / "v11-e2e.json"
    commands: list[CommandEvidence] = []
    print(
        f"[qualification] START iteration={iteration_id} mode={mode} "
        f"source={fingerprint_before[:12]}",
        flush=True,
    )
    for name, argv in command_plan(mode, e2e_path):
        print(f"[qualification] START command={name}", flush=True)
        evidence = run_command(name, argv, timeout)
        commands.append(evidence)
        print(
            f"[qualification] {'PASS' if evidence.passed else 'FAIL'} "
            f"command={name} duration={evidence.duration_seconds}s "
            f"exit={evidence.returncode} timeout={evidence.timed_out}",
            flush=True,
        )
        if not evidence.passed:
            break
    e2e_result = None
    if e2e_path.exists():
        try:
            e2e_result = json.loads(e2e_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            e2e_result = {"passed": False, "error": f"invalid E2E JSON: {exc}"}
    fingerprint_after = source_fingerprint()
    stale = fingerprint_before != fingerprint_after
    previous = store.previous()
    passed = (
        not stale
        and bool(commands)
        and all(command.passed for command in commands)
        and (mode == "tests-only" or bool(e2e_result and e2e_result.get("passed")))
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
        e2e_result=e2e_result,
        regression_delta=_regression_delta(previous, commands, e2e_result),
        passed=passed,
    )
    store.write(result)
    return result


def _wait_for_stable_change(baseline: str, debounce_seconds: float) -> str:
    while True:
        time.sleep(min(0.5, max(0.1, debounce_seconds)))
        current = source_fingerprint()
        if current == baseline:
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
    pending = True
    last_result: IterationEvidence | None = None
    while pending or args.watch:
        if pending:
            last_result = run_iteration(store, mode, args.timeout, changed)
            count += 1
            print(_canonical_json({
                "iteration_id": last_result.iteration_id,
                "passed": last_result.passed,
                "stale": last_result.stale,
                "source": last_result.source_fingerprint_before,
            }), flush=True)
            baseline = last_result.source_fingerprint_after
            pending = last_result.stale
            changed = ()
            if args.max_iterations and count >= args.max_iterations:
                break
            if not args.watch and not pending:
                break
            continue
        new_fingerprint = _wait_for_stable_change(baseline, args.debounce_seconds)
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
    parser.add_argument("--max-iterations", type=int, default=0)
    args = parser.parse_args(argv)
    if not args.once and not args.watch:
        args.once = True
    if args.debounce_seconds < 0 or args.timeout <= 0 or args.max_iterations < 0:
        parser.error("debounce/timeout/max-iterations must be non-negative and timeout must be positive")
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
