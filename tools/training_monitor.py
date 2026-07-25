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
EXAM_BAT = ROOT / "RUN-PROBE-EXAM.bat"
FLYWHEEL_BAT = ROOT / "START-FLYWHEEL-LOOP.bat"
FLYWHEEL_LOG = ROOT / "bench" / "flywheel-log.txt"
FLYWHEEL_STATE = ROOT / "bench" / "flywheel-state.json"

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


def _newest_results_file() -> Path | None:
    best = None
    for rf in BENCH_DIR.glob("results-*.json"):
        m = TIMESTAMP_RE.search(rf.name)
        if not m:
            continue
        ts = time.mktime(time.strptime(m.group(1), "%Y%m%dT%H%M%S"))
        if best is None or ts > best[0]:
            best = (ts, rf)
    return best[1] if best else None


def _scan_history() -> list[dict]:
    """Match each trained generation to the exam that graded it.

    Two other things now write results-*.json besides a real exam: the
    llama3.1 harvester's routine batches and the flywheel's cloud-lane
    top-up - both 15 prompts, neither a real llama3.1-vs-probe comparison.
    So this has to be specific about what it trusts:
      - trained-lane data: only the literal "planner-probe-v1" lane counts -
        a glm-5.2:cloud or kimi-k2.6:cloud top-up file is NOT a probe result
        just because it isn't llama3.1 either.
      - baseline data: only a llama3.1 lane from a real, full-size exam
        (>=20 prompts) counts - a 15-prompt harvester/top-up batch contains
        llama3.1 too but isn't a comparable baseline reading.
    Baseline is no longer in every exam - run_chain.py now only refreshes it
    every 5th cycle or right after a solver/pipeline change (see
    _decide_exam_lanes there). So a generation's own result file may carry
    ONLY its trained lane; pair it with the most recent valid baseline seen
    in ANY results file up to that point, instead of requiring both lanes
    to land in the same file."""
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
    parsed_results.sort()

    def latest_baseline_at_or_before(ts_cutoff):
        best = None
        for ts, rf in parsed_results:
            if ts > ts_cutoff:
                continue
            data = _read_json(rf)
            if not data or "lanes" not in data:
                continue
            base = data["lanes"].get("llama3.1")
            total = data.get("prompts")
            if not base or not total or total < 20:
                continue  # a real comparison exam, not a 15-prompt harvester/top-up batch
            if base.get("total") != total:
                continue  # still in progress
            if best is None or ts > best[0]:
                best = (ts, base)
        return best[1] if best else None

    for run in runs:
        best_trained = None  # (ts, trained_lane_dict)
        for ts, rf in parsed_results:
            if ts < run["trained_epoch"] or (best_trained is not None and ts <= best_trained[0]):
                continue
            data = _read_json(rf)
            if not data or "lanes" not in data:
                continue
            trained_lane = data["lanes"].get("planner-probe-v1")  # the ONLY lane that IS the probe
            total = data.get("prompts")
            # Only a FULLY FINISHED trained-lane result counts - an exam
            # still in progress must never bump a complete older result off
            # the table. Once this generation gets re-benched to completion
            # it wins on recency automatically.
            if not trained_lane:
                continue
            if total and trained_lane.get("total") != total:
                continue
            best_trained = (ts, trained_lane)

        run["exam"] = None
        if best_trained:
            ts, trained_lane = best_trained
            base = latest_baseline_at_or_before(ts)
            run["exam"] = {
                "baseline_rate": base.get("legal_rate") if base else None,
                "baseline_legal": base.get("legal") if base else None,
                "baseline_total": base.get("total") if base else None,
                "trained_rate": trained_lane.get("legal_rate", 0.0),
                "trained_legal": trained_lane.get("legal", 0),
                "trained_total": trained_lane.get("total", 0),
            }
    return list(reversed(runs))


CORPUS_FILES = (ROOT / "data" / "flywheel" / "corpus.jsonl",
                ROOT / "data" / "flywheel" / "corpus-bench.jsonl")


def _corpus_composition() -> dict:
    """Organic (harvested from the llama3.1 loop) vs synthetic (cloud-lane
    top-up) rows in the corpus right now, and how many actually pass
    validation - the SAME passed/failed check make_training_set.py uses, so
    this always matches what training really sees, never a separate guess."""
    organic = synthetic = other = accepted = 0
    for p in CORPUS_FILES:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            lane = d.get("model_lane") or ""
            if lane == "llama3.1":
                organic += 1
            elif "cloud" in lane:
                synthetic += 1
            else:
                other += 1
            verdict = (d.get("per_gate_verdicts") or {}).get("plan")
            status = verdict.get("status") if isinstance(verdict, dict) else verdict
            if status in ("passed", "pass"):
                accepted += 1
    return {"organic": organic, "synthetic": synthetic, "other": other,
            "accepted": accepted, "total": organic + synthetic + other}


class TrainingMonitor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Training Monitor - The Living Room")
        self.geometry("920x920")
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
        self.exam_btn = tk.Button(btn_row, text="Run exam now (llama3.1 vs probe)",
                                   command=self._start_exam, bg="#2a3140", fg="#e8eaf0",
                                   activebackground="#37405a", relief="flat", padx=12, pady=6)
        self.exam_btn.pack(side="left", padx=(8, 0))
        self.flywheel_btn = tk.Button(btn_row, text="Start flywheel loop (auto train+exam)",
                                       command=self._start_flywheel, bg="#2a3140", fg="#e8eaf0",
                                       activebackground="#37405a", relief="flat", padx=12, pady=6)
        self.flywheel_btn.pack(side="left", padx=(8, 0))
        self.updated_var = tk.StringVar(value="")
        tk.Label(btn_row, textvariable=self.updated_var, font=("Segoe UI", 9),
                 bg="#191d27", fg="#6f7a90").pack(side="right")

        self.exam_status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.exam_status_var, font=("Segoe UI", 9),
                 bg="#191d27", fg="#7f8ba3", wraplength=860, justify="left").pack(
            fill="x", padx=14, pady=(0, 4))

        self.flywheel_status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.flywheel_status_var, font=("Segoe UI", 9),
                 bg="#191d27", fg="#7f8ba3", wraplength=860, justify="left").pack(
            fill="x", padx=14, pady=(0, 4))

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

        chart_frame = tk.LabelFrame(
            self, text="Plan-legality rate by generation (the loop's real, measured metric)",
            font=("Segoe UI", 10, "bold"), bg="#1b2029", fg="#c6d0e2", bd=1)
        chart_frame.pack(fill="x", **pad)
        self.chart = tk.Canvas(chart_frame, width=860, height=170, bg="#191d27", highlightthickness=0)
        self.chart.pack(padx=10, pady=(8, 2))
        tk.Label(chart_frame,
                 text="Green = trained probe. Gray dashed = llama3.1 baseline (only re-checked "
                      "every 5th cycle, so some points won't have one yet). This is the loop's "
                      "real metric: does a plan pass validation? It does NOT measure rendering, "
                      "walking, or the playable game itself - that's the separate 3D World "
                      "pipeline at localhost:5173, not something this training loop touches.",
                 font=("Segoe UI", 8), bg="#1b2029", fg="#7f8ba3", wraplength=840,
                 justify="left").pack(padx=10, pady=(0, 6), anchor="w")
        self.composition_var = tk.StringVar(value="")
        tk.Label(chart_frame, textvariable=self.composition_var, font=("Segoe UI", 9),
                 bg="#1b2029", fg="#aab2c5", wraplength=840, justify="left").pack(
            padx=10, pady=(0, 8), anchor="w")

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

    def _start_exam(self):
        if not EXAM_BAT.exists():
            self.exam_status_var.set(f"Can't find {EXAM_BAT.name} in the project folder.")
            return
        subprocess.Popen(["cmd", "/c", "start", "", str(EXAM_BAT)], cwd=str(ROOT))
        self.exam_status_var.set(
            "Launched RUN-PROBE-EXAM.bat - 30 prompts x 2 lanes, roughly 30-60 minutes. "
            "The table above updates on its own when the new result lands.")

    def _start_flywheel(self):
        if not FLYWHEEL_BAT.exists():
            self.flywheel_status_var.set(f"Can't find {FLYWHEEL_BAT.name} in the project folder.")
            return
        subprocess.Popen(["cmd", "/c", "start", "", str(FLYWHEEL_BAT)], cwd=str(ROOT))
        self.flywheel_status_var.set(
            "Launched START-FLYWHEEL-LOOP.bat - runs minimized, forever, until you pause it "
            "(create bench\\PAUSE-FLYWHEEL.txt to stop it).")

    # ---- polling ----
    def _tick(self):
        self._update_stage()
        self._update_machine()
        self._update_exam()
        self._update_flywheel()
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

    def _update_exam(self):
        """Live exam progress - now possible because plan_bench.py saves
        after every prompt, not just once per 30-prompt lane. Only touches
        exam_status_var when there's real fresh data to show; otherwise
        leaves whatever message (e.g. the just-launched one) already there."""
        rf = _newest_results_file()
        if not rf or not rf.exists():
            return
        data = _read_json(rf)
        if not data:
            return
        age = time.time() - rf.stat().st_mtime
        if "finished" in data:
            if age < 60:
                self.exam_status_var.set(f"Exam finished ({rf.name}) - see the table below.")
            return
        if age > 300:
            return  # stale/abandoned run - don't overwrite the last real message
        total = data.get("prompts", "?")
        parts = [f"{lane}: {v.get('total', 0)}/{total} done ({v.get('legal', 0)} legal so far)"
                 for lane, v in data.get("lanes", {}).items()]
        if parts:
            self.exam_status_var.set("Exam running - " + " | ".join(parts))

    def _update_flywheel(self):
        """Live status for the continuous train<->exam loop, if it's running."""
        if not FLYWHEEL_LOG.exists():
            self.flywheel_status_var.set("Flywheel loop: not started yet.")
            return
        last = _tail_last_line(FLYWHEEL_LOG)
        if not last:
            self.flywheel_status_var.set("Flywheel loop: not started yet.")
            return
        m = CHAIN_LINE_RE.match(last)
        body = m.group(2) if m else last
        age = time.time() - FLYWHEEL_LOG.stat().st_mtime
        stale = "  (no update in 15+ min - may be paused or stopped)" if age > 900 else ""
        self.flywheel_status_var.set(f"Flywheel loop: {body}{stale}")

    def _draw_chart(self, runs: list[dict]) -> None:
        c = self.chart
        c.delete("all")
        w, h = int(c["width"]), int(c["height"])
        pad_l, pad_r, pad_t, pad_b = 42, 16, 14, 22
        plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b

        for pct in (0, 25, 50, 75, 100):
            y = pad_t + plot_h * (1 - pct / 100)
            c.create_line(pad_l, y, w - pad_r, y, fill="#2a3140")
            c.create_text(pad_l - 6, y, text=f"{pct}%", fill="#7f8ba3",
                          font=("Segoe UI", 8), anchor="e")
        c.create_line(pad_l, pad_t, pad_l, h - pad_b, fill="#3a4358")
        c.create_line(pad_l, h - pad_b, w - pad_r, h - pad_b, fill="#3a4358")

        points = [r for r in reversed(runs) if r.get("exam")]  # chronological, left -> right
        if not points:
            c.create_text(w / 2, h / 2, text="No benched generations yet",
                          fill="#7f8ba3", font=("Segoe UI", 9))
            return

        n = len(points)
        xs = [pad_l + (plot_w * i / max(n - 1, 1)) for i in range(n)]

        def y_of(rate):
            return pad_t + plot_h * (1 - max(0.0, min(1.0, rate)))

        prev = None
        for x, r in zip(xs, points):
            exam = r["exam"]
            if exam["baseline_rate"] is not None:
                y = y_of(exam["baseline_rate"])
                if prev:
                    c.create_line(prev[0], prev[1], x, y, fill="#7f8ba3", dash=(3, 2))
                c.create_oval(x - 3, y - 3, x + 3, y + 3, outline="#7f8ba3", fill="#191d27")
                prev = (x, y)
            else:
                prev = None

        prev = None
        for x, r in zip(xs, points):
            y = y_of(r["exam"]["trained_rate"])
            if prev:
                c.create_line(prev[0], prev[1], x, y, fill="#3ddc84", width=2)
            c.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#3ddc84", outline="")
            prev = (x, y)

        for x, r in zip(xs, points):
            label = time.strftime("%m/%d", time.localtime(r["trained_epoch"]))
            c.create_text(x, h - pad_b + 10, text=label, fill="#7f8ba3", font=("Segoe UI", 8))

    def _update_history(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        runs = _scan_history()
        self._draw_chart(runs)
        comp = _corpus_composition()
        self.composition_var.set(
            f"Corpus right now: {comp['organic']} organic (llama3.1 harvester) + "
            f"{comp['synthetic']} synthetic (cloud top-up) + {comp['other']} from earlier "
            f"pipeline runs = {comp['total']} rows -> {comp['accepted']} pass validation "
            f"and become trainable exemplars.")
        if not runs:
            self.tree.insert("", "end", values=("No trained generations yet", "", "", "", ""))
            return
        for run in runs:
            exam = run.get("exam")
            trained_at = time.strftime("%b %d %H:%M", time.localtime(run["trained_epoch"]))
            if not exam:
                self.tree.insert("", "end", values=(run["name"], trained_at, "not benched yet", "-", "-"))
                continue
            trained_txt = f"{exam['trained_legal']}/{exam['trained_total']} ({exam['trained_rate']*100:.0f}%)"
            if exam["baseline_rate"] is None:
                self.tree.insert("", "end", values=(run["name"], trained_at, "no baseline yet", trained_txt, "-"))
                continue
            base_txt = f"{exam['baseline_legal']}/{exam['baseline_total']} ({exam['baseline_rate']*100:.0f}%)"
            delta = exam["trained_rate"] - exam["baseline_rate"]
            verdict = "improved" if delta > 0.03 else ("about the same" if delta > -0.03 else "worse")
            self.tree.insert("", "end", values=(run["name"], trained_at, base_txt, trained_txt, verdict))


if __name__ == "__main__":
    TrainingMonitor().mainloop()
