"""Training Monitor - a small desktop app that shows the LoRA retraining
process for this project's planner model, live, plus the raw CPU/GPU/RAM
your machine is spending on it.

Reads only - never fabricates a number:
  - output/qualification/telemetry.json     -> live CPU/GPU/RAM
  - bench/chain-log.txt                     -> coarse stage (its last line)
  - bench/training-progress.json            -> real step/epoch/loss, written
                                                by bench/train_probe.py's own
                                                trainer callback
  - bench/trained/*/ + bench/results-*.json -> history: each trained
                                                generation vs. plain llama3.1

"Start new training run" launches the existing, proven RUN-TRAINING-CHAIN.bat.
This app does not reimplement the GPU-wait / train / save logic - it only
watches it.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parent.parent
TELEMETRY = ROOT / "output" / "qualification" / "telemetry.json"
CHAIN_LOG = ROOT / "bench" / "chain-log.txt"
PROGRESS = ROOT / "bench" / "training-progress.json"
TRAINED_DIR = ROOT / "bench" / "trained"
BENCH_DIR = ROOT / "bench"
RUN_CHAIN_BAT = ROOT / "RUN-TRAINING-CHAIN.bat"

POLL_MS = 1500
HISTORY_REFRESH_S = 15

STAGE_LABELS = {
    "loading_model": "Loading the base model (llama-3.1-8B, 4-bit)...",
    "training": "Training now (the ~7 minute part)...",
    "saving_gguf": "Saving the trained model to disk...",
    "done": "Finished - ready to bench against llama3.1",
}

CHAIN_LINE_RE = re.compile(r"^\[(\d\d:\d\d:\d\d)\]\s*(.*)$")
TIMESTAMP_RE = re.compile(r"(\d{8}T\d{6})")


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _tail_last_line(path: Path) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return lines[-1] if lines else None
    except Exception:
        return None


def _is_terminal(body: str) -> bool:
    """True once a chain run has ended, one way or another (run_chain.py
    prints 'train_probe finished rc=N', then only on success a 'SUCCESS' line -
    so the file's very last line can be either one)."""
    return body.startswith("SUCCESS") or "finished rc=" in body


def _coarse_stage(last_line: str | None) -> str:
    if not last_line:
        return "No training run has been started yet."
    m = CHAIN_LINE_RE.match(last_line)
    body = m.group(2) if m else last_line
    if body.startswith("SUCCESS") or "finished rc=0" in body:
        return "Last run finished successfully."
    if "finished rc=" in body:
        return "Last run FAILED - see bench\\chain-log.txt"
    if "training probe starting" in body:
        return STAGE_LABELS["training"]
    if "building training set" in body:
        return "Building the training set from your corpus..."
    if "claiming the GPU" in body:
        return "Claiming the GPU..."
    if "quiet check" in body:
        return f"Waiting for a quiet GPU... ({body.split('quiet check', 1)[1].strip()})"
    if "waiting" in body:
        return "Waiting for a quiet GPU..."
    if "chain started" in body:
        return "Starting..."
    return body


def _scan_history() -> list[dict]:
    """Match each trained generation to the exam that graded it."""
    if not TRAINED_DIR.exists():
        return []
    runs = []
    for d in sorted(TRAINED_DIR.iterdir()):
        if not d.is_dir() or d.name.endswith("_gguf"):
            continue
        m = TIMESTAMP_RE.search(d.name)
        if not m:
            continue
        trained_epoch = time.mktime(time.strptime(m.group(1), "%Y%m%dT%H%M%S"))
        runs.append({"name": d.name, "trained_epoch": trained_epoch})

    parsed_results = []
    for rf in BENCH_DIR.glob("results-*.json"):
        m = TIMESTAMP_RE.search(rf.name)
        if not m:
            continue
        ts = time.mktime(time.strptime(m.group(1), "%Y%m%dT%H%M%S"))
        parsed_results.append((ts, rf))

    for run in runs:
        best = None
        for ts, rf in parsed_results:
            if ts >= run["trained_epoch"] and (best is None or ts < best[0]):
                best = (ts, rf)
        run["exam"] = None
        if best:
            data = _read_json(best[1])
            if data and "lanes" in data:
                base = data["lanes"].get("llama3.1")
                trained_lane = next((v for k, v in data["lanes"].items() if k != "llama3.1"), None)
                if base and trained_lane:
                    run["exam"] = {
                        "baseline_rate": base.get("legal_rate", 0.0),
                        "baseline_legal": base.get("legal", 0),
                        "baseline_total": base.get("total", 0),
                        "trained_rate": trained_lane.get("legal_rate", 0.0),
                        "trained_legal": trained_lane.get("legal", 0),
                        "trained_total": trained_lane.get("total", 0),
                    }
    return list(reversed(runs))


class TrainingMonitor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Training Monitor - The Living Room")
        self.geometry("760x640")
        self.configure(bg="#191d27")
        self._last_history = 0.0
        self._build_ui()
        self._update_history()
        self._tick()

    # ---- UI ----
    def _build_ui(self):
        pad = {"padx": 14, "pady": 8}
        header = tk.Frame(self, bg="#191d27")
        header.pack(fill="x", **pad)
        tk.Label(header, text="Planner training (LoRA fine-tune)", font=("Segoe UI", 14, "bold"),
                 bg="#191d27", fg="#e8eaf0").pack(anchor="w")
        self.stage_var = tk.StringVar(value="Checking...")
        tk.Label(header, textvariable=self.stage_var, font=("Segoe UI", 11),
                 bg="#191d27", fg="#aab2c5").pack(anchor="w", pady=(2, 8))

        self.progress = ttk.Progressbar(header, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.progress_detail = tk.StringVar(value="")
        tk.Label(header, textvariable=self.progress_detail, font=("Segoe UI", 9),
                 bg="#191d27", fg="#7f8ba3").pack(anchor="w", pady=(2, 0))

        btn_row = tk.Frame(self, bg="#191d27")
        btn_row.pack(fill="x", **pad)
        self.start_btn = tk.Button(btn_row, text="Start new training run",
                                    command=self._start_training, bg="#2d6cdf", fg="white",
                                    activebackground="#254070", relief="flat", padx=12, pady=6)
        self.start_btn.pack(side="left")
        self.updated_var = tk.StringVar(value="")
        tk.Label(btn_row, textvariable=self.updated_var, font=("Segoe UI", 9),
                 bg="#191d27", fg="#6f7a90").pack(side="right")

        gpu_frame = tk.LabelFrame(self, text="Your machine, right now", font=("Segoe UI", 10, "bold"),
                                   bg="#1b2029", fg="#c6d0e2", bd=1)
        gpu_frame.pack(fill="x", **pad)
        self.machine_bars = {}
        for key, label in [("cpu", "CPU"), ("ram", "RAM"), ("gpu", "GPU"), ("vram", "VRAM")]:
            row = tk.Frame(gpu_frame, bg="#1b2029")
            row.pack(fill="x", padx=10, pady=4)
            tk.Label(row, text=label, width=6, anchor="w", bg="#1b2029", fg="#aab2c5",
                     font=("Segoe UI", 9)).pack(side="left")
            bar = ttk.Progressbar(row, mode="determinate", maximum=100, length=300)
            bar.pack(side="left", padx=(0, 10))
            val = tk.StringVar(value="-")
            tk.Label(row, textvariable=val, bg="#1b2029", fg="#e8eaf0",
                     font=("Segoe UI", 9)).pack(side="left")
            self.machine_bars[key] = (bar, val)

        hist_frame = tk.LabelFrame(self, text="Trained generations vs. plain llama3.1",
                                    font=("Segoe UI", 10, "bold"), bg="#1b2029", fg="#c6d0e2", bd=1)
        hist_frame.pack(fill="both", expand=True, **pad)
        cols = ("generation", "trained", "baseline", "trained_rate", "verdict")
        self.tree = ttk.Treeview(hist_frame, columns=cols, show="headings", height=8)
        headers = {"generation": "Generation", "trained": "Trained", "baseline": "llama3.1 (base)",
                   "trained_rate": "Trained probe", "verdict": "Verdict"}
        widths = {"generation": 170, "trained": 130, "baseline": 130, "trained_rate": 130, "verdict": 140}
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TProgressbar", background="#3ddc84", troughcolor="#2a3140")

    # ---- actions ----
    def _start_training(self):
        if not RUN_CHAIN_BAT.exists():
            self.stage_var.set(f"Can't find {RUN_CHAIN_BAT.name} in the project folder.")
            return
        subprocess.Popen(["cmd", "/c", "start", "", str(RUN_CHAIN_BAT)], cwd=str(ROOT))
        self.stage_var.set("Launched RUN-TRAINING-CHAIN.bat - it waits for a quiet GPU on its own.")

    # ---- polling ----
    def _tick(self):
        self._update_stage()
        self._update_machine()
        if time.time() - self._last_history > HISTORY_REFRESH_S:
            self._update_history()
            self._last_history = time.time()
        self.updated_var.set("updated " + time.strftime("%H:%M:%S"))
        self.after(POLL_MS, self._tick)

    def _update_stage(self):
        prog = _read_json(PROGRESS)
        last_line = _tail_last_line(CHAIN_LOG)
        coarse = _coarse_stage(last_line)

        active = False
        if CHAIN_LOG.exists() and last_line:
            m = CHAIN_LINE_RE.match(last_line)
            body = m.group(2) if m else last_line
            age = time.time() - CHAIN_LOG.stat().st_mtime
            active = age < 180 and not _is_terminal(body)
        self.start_btn.config(state="disabled" if active else "normal")

        if prog and prog.get("stage") in STAGE_LABELS:
            fresh = (time.time() - prog.get("updated", 0)) < 120
            if fresh and prog["stage"] == "training" and prog.get("max_steps"):
                pct = 100.0 * (prog.get("step", 0) / max(prog["max_steps"], 1))
                self.progress["value"] = pct
                loss = prog.get("loss")
                loss_txt = f", loss {loss:.3f}" if isinstance(loss, (int, float)) else ""
                self.progress_detail.set(
                    f"step {prog.get('step', 0)}/{prog['max_steps']} "
                    f"(epoch {prog.get('epoch', 0)}){loss_txt} - {prog.get('rows', '?')} training rows")
                self.stage_var.set(STAGE_LABELS["training"])
                return
            if fresh:
                self.stage_var.set(STAGE_LABELS[prog["stage"]])
                self.progress["value"] = 100 if prog["stage"] == "done" else 0
                self.progress_detail.set(f"{prog.get('rows', '?')} training rows")
                return

        self.stage_var.set(coarse)
        self.progress["value"] = 100 if "finished successfully" in coarse else 0
        self.progress_detail.set("")

    def _update_machine(self):
        t = _read_json(TELEMETRY)
        if not t:
            for bar, val in self.machine_bars.values():
                bar["value"] = 0
                val.set("no telemetry")
            return
        age = time.time() - t.get("ts", 0)
        totals = t.get("totals", {})
        stale = " (stale)" if age > 30 else ""
        mapping = {
            "cpu": (totals.get("cpu_pct", 0), f"{totals.get('cpu_pct', 0):.0f}%{stale}"),
            "ram": (100 * totals.get("ram_used_gb", 0) / max(totals.get("ram_total_gb", 1), 1),
                    f"{totals.get('ram_used_gb', 0):.1f} / {totals.get('ram_total_gb', 0):.0f} GB"),
            "gpu": (totals.get("gpu_util_pct", 0), f"{totals.get('gpu_util_pct', 0):.0f}%{stale}"),
            "vram": (100 * totals.get("vram_used_gb", 0) / max(totals.get("vram_total_gb", 1), 1),
                     f"{totals.get('vram_used_gb', 0):.1f} / {totals.get('vram_total_gb', 0):.0f} GB"),
        }
        for key, (pct, text) in mapping.items():
            bar, val = self.machine_bars[key]
            bar["value"] = max(0, min(100, pct))
            val.set(text)

    def _update_history(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        runs = _scan_history()
        if not runs:
            self.tree.insert("", "end", values=("No trained generations yet", "", "", "", ""))
            return
        for run in runs:
            exam = run.get("exam")
            trained_at = time.strftime("%b %d %H:%M", time.localtime(run["trained_epoch"]))
            if not exam:
                self.tree.insert("", "end", values=(run["name"], trained_at, "not benched yet", "-", "-"))
                continue
            base_txt = f"{exam['baseline_legal']}/{exam['baseline_total']} ({exam['baseline_rate']*100:.0f}%)"
            trained_txt = f"{exam['trained_legal']}/{exam['trained_total']} ({exam['trained_rate']*100:.0f}%)"
            delta = exam["trained_rate"] - exam["baseline_rate"]
            verdict = "improved" if delta > 0.03 else ("about the same" if delta > -0.03 else "worse")
            self.tree.insert("", "end", values=(run["name"], trained_at, base_txt, trained_txt, verdict))


if __name__ == "__main__":
    TrainingMonitor().mainloop()
