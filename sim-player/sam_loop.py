"""sim-player/sam_loop.py — the Sam Loop runner: play → analyze → (route gaps) → (the mechanic) → restart → again.

John's depth "C" (2026-09-10): while he sleeps, Sam plays his own copy of the neighborhood on the
loop's own Living Room (:8001), every round is analyzed, unmet wishes go to the capability-gaps
ledger (and at depth B/C the gap router pushes the "things" to the factory), defects go to the
mechanic (depth C), and if the mechanic's patch passed the gate the sim Living Room is restarted so
the next round proves the fix. John's :8000 is never touched by this file.

The night-shift laws it keeps (CLAUDE.md 2B): every dependency is started or waited for at every
start and resume — Ollama, the Pick Board, the builder, the sim Living Room (an outage is a wait,
never a lane failure); rounds are time-boxed and leftovers stay queued; a STOP file ends the loop
between rounds; pause windows (sim-player/pause-windows.txt, lines like 02:00-03:30) are honoured;
spawned servers get their own console group and no window; a heartbeat file says what it is doing.

    python sam_loop.py --once --depth A            # one round: play + analyze + file gaps, then stop
    python sam_loop.py --rounds 8 --depth C        # the night (add --factory to let the router push things to the 4090)
    python sam_loop.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import sam  # noqa: E402
import seed_world  # noqa: E402
import analysis  # noqa: E402
import mechanic  # noqa: E402
import remember  # noqa: E402
import sim_board
try:
    import consolidate
except Exception:   # the loop runs with or without it
    consolidate = None  # noqa: E402

CEO_DIR = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc")
# 2026-09-11: the loop used to START JOHN'S OWN Pick Board if it was down. It no longer touches it —
# Sam runs his own (sim_board.py). John's :8194 can be up, down or mid-restart and the night is
# unaffected, and nothing Sam decides can land in John's stations or his taste ledger.
# what Sam carries from one night to the next. Resolved at CALL time, next to the round folders:
# the tests move common.RUNS, and a head frozen at import would write into the real one.
def sam_head() -> Path:
    return common.RUNS / "sam-head.json"
BUILDER_BAT = Path(r"E:\Software Development\Video Game Development\03 Projects\Cul-de-sac\START-NEIGHBOURHOOD-BUILDER.bat")
EVENTS_SIM = CEO_DIR / "training-data" / "events-sim.jsonl"
OLLAMA_APPS = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama app.exe"),
               os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")]
STOP = common.HERE / "STOP"
# ── THE DIAL ────────────────────────────────────────────────────────────────
# 2026-09-14, John: "make the next batch smaller and easier to control."
#
# --batch sets where it STARTS. This file is what it listens to, and it is read fresh at the top of
# every round, so changing the number takes effect on the next round with no restart, no window to
# find and no work lost. That matters because the right batch size is not knowable in advance: too
# big and a bad lesson poisons forty nights, too small and every lesson is noise from six rounds.
# It should be adjustable while watching, which means adjustable without stopping.
#
#   {"batch": 10}      consolidate every 10 rounds
#   {"batch": 0}       keep playing, never consolidate
#
# A missing file, a broken file or a silly number all mean "leave it as it is" — this dial can slow
# the learning down but it can never stop the night.
CONTROL = common.HERE / "loop-control.json"
BATCH_MAX = 200


def batch_size(current: int) -> int:
    """The batch size right now. `current` is returned unchanged if the file says nothing usable."""
    try:
        want = json.loads(CONTROL.read_text(encoding="utf-8")).get("batch")
    except Exception:                       # noqa: BLE001 — no file, bad JSON, locked file: all the same
        return current
    if not isinstance(want, int) or isinstance(want, bool) or not (0 <= want <= BATCH_MAX):
        return current
    return want


def set_batch(n: int, why: str = "") -> int:
    """Write the dial. Used by the dashboard and the dev server; safe to call while the loop runs."""
    n = max(0, min(BATCH_MAX, int(n)))
    try:
        CONTROL.write_text(json.dumps({"batch": n, "at": common.now_iso(), "why": why}, indent=1),
                           encoding="utf-8")
    except OSError:
        pass
    return n
PAUSE_WINDOWS = common.HERE / "pause-windows.txt"
SIM_PORT = int(os.getenv("SAM_PORT", "8001"))
MAX_GAPS_ROUTED = 5                       # the factory gets at most this many new things per round
DETACHED = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
# 2026-09-14: EVERY SHORT-LIVED CHILD GETS THIS TOO, and here is why it started mattering today.
# When the loop runs from a .bat it owns a console window, and netstat, nvidia-smi, taskkill and the
# rest inherit it silently. Started headless — which is how it is started now, from the dev server —
# the loop has NO console, so Windows CREATES ONE for each child that does not say otherwise, and
# John watches a terminal window flash open and shut every few seconds all night. It is cosmetic and
# it is unbearable, and it is entirely our doing. CREATE_NO_WINDOW on every one of them.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def log(msg: str) -> None:
    common.log(msg, file=common.RUNS / "loop-log.txt")       # resolved at call time: tests move RUNS


def heartbeat(**kw) -> None:
    common.RUNS.mkdir(parents=True, exist_ok=True)
    try:
        (common.RUNS / "heartbeat.json").write_text(json.dumps({"at": common.now_iso(), "pid": os.getpid(), **kw}, indent=1), encoding="utf-8")
    except OSError:
        pass


# ── pause and stop ────────────────────────────────────────────────────────────────────────────
def in_pause_window(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    try:
        lines = [l.strip() for l in PAUSE_WINDOWS.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    except OSError:
        return False
    hm = now.hour * 60 + now.minute
    for line in lines:
        try:
            a, b = line.split("-"); a = int(a[:2]) * 60 + int(a[3:5]); b = int(b[:2]) * 60 + int(b[3:5])
        except Exception:
            continue
        if (a <= hm < b) if a <= b else (hm >= a or hm < b):
            return True
    return False


def wait_if_paused() -> None:
    while in_pause_window():
        heartbeat(phase="paused (pause-windows.txt)")
        time.sleep(60)


# ── dependencies: start or wait, never fail the round ─────────────────────────────────────────
def _up(url: str, timeout: float = 5.0) -> bool:
    try:
        st, _ = common.http_json("GET", url, timeout=timeout)
    except common.Backend:
        return False
    return st == 200


# ── WHICH PYTHON RUNS THE LIVING ROOM ───────────────────────────────────────
# 2026-09-14. The loop was started by something whose PATH resolves a different `python` than the
# .bat files do, and Sam's Living Room died on `import uvicorn` every two minutes for eleven
# minutes straight. The heartbeat kept writing, `alive` kept saying true, and zero rounds were
# played: a loop wedged this way looks perfectly healthy from outside.
#
# So the interpreter for run.py is CHOSEN, not inherited. sys.executable first, because when the
# loop is started from a .bat that is already the right answer; then the py launcher; then PATH;
# then the usual install roots. The test is the only one that matters — can it import uvicorn.
# Cached for the life of the process, and logged, so the answer is never a mystery again.
_LIVING_ROOM_PY: str | None = None


def living_room_python() -> str | None:
    """A python on this machine that can actually run run.py, or None if there is not one."""
    global _LIVING_ROOM_PY
    if _LIVING_ROOM_PY:
        return _LIVING_ROOM_PY
    seen, cands = set(), [sys.executable, "py", "python", "python3"]
    for root in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python"),
                 r"C:\Program Files", "C:\\"):
        try:
            for name in sorted(os.listdir(root), reverse=True):     # newest version first
                if name.lower().startswith("python"):
                    cands.append(os.path.join(root, name, "python.exe"))
        except OSError:
            continue
    tried = []
    for exe in cands:
        if not exe or exe in seen:
            continue
        seen.add(exe)
        if exe.endswith(".exe") and not os.path.isfile(exe):
            continue
        try:
            p = subprocess.run([exe, "-c", "import uvicorn,sys;print(sys.executable)"],
                               capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
            tried.append((exe, p.returncode))
            if p.returncode == 0:
                _LIVING_ROOM_PY = exe
                log(f"the Living Room will run on {p.stdout.strip() or exe}")
                return exe
        except Exception as e:                  # noqa: BLE001 — a candidate that explodes is just a no
            tried.append((exe, str(e)[:40]))
    log("NO python on this machine can import uvicorn — the Living Room cannot start. Tried: "
        + ", ".join(f"{e}({r})" for e, r in tried[:8]))
    return None


def _spawn(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> subprocess.Popen | None:
    try:
        return subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, env=env, creationflags=DETACHED, close_fds=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f"could not start {cmd[0]}: {e}")
        return None


def _wait(url: str, wait_s: float, what: str) -> bool:
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if _up(url):
            log(f"{what} is up after {int(time.time() - t0)} s")
            return True
        time.sleep(5)
    log(f"{what} still not answering after {int(wait_s)} s")
    return False


def ensure_ollama(wait_s: float = 150) -> bool:
    if _up(common.OLLAMA + "/api/tags"):
        return True
    cmd = None
    for p in OLLAMA_APPS:
        if os.path.exists(p):
            cmd = [p] if p.endswith("app.exe") else [p, "serve"]; break
    if cmd is None and shutil.which("ollama"):
        cmd = [shutil.which("ollama"), "serve"]
    if cmd is None:
        log("Ollama is down and no launcher was found — looked in: " + " | ".join(OLLAMA_APPS) + " | PATH"); return False
    log("Ollama is down — starting it: " + " ".join(cmd))
    _spawn(cmd)
    return _wait(common.OLLAMA + "/api/tags", wait_s, "Ollama")


def ensure_bat_service(url: str, bat: Path, what: str, wait_s: float) -> bool:
    if _up(url):
        return True
    if not bat.exists():
        log(f"{what} is down and its launcher is missing: {bat}"); return False
    log(f"{what} is down — starting {bat.name}")
    _spawn(["cmd", "/c", "call", str(bat)], cwd=bat.parent)
    return _wait(url, wait_s, what)


def _port_owner(port: int) -> int | None:
    """PID listening on the port (Windows netstat), or None."""
    try:
        out = subprocess.run(["netstat", "-aon"], capture_output=True, text=True, timeout=20,
                             creationflags=NO_WINDOW).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
            try:
                return int(parts[4])
            except ValueError:
                return None
    return None


def _cmdline(pid: int) -> str:
    try:
        out = subprocess.run(["wmic", "process", "where", f"processid={pid}", "get", "CommandLine", "/value"],
                             creationflags=NO_WINDOW,
                             capture_output=True, text=True, timeout=20).stdout
        if out.strip():
            return out.strip()
    except Exception:
        pass
    # wmic has been REMOVED from current Windows builds. It returned "" here, silently, and because
    # every guard below is "kill only what I can prove is mine", a blind reader means nothing is ever
    # provable and nothing is ever freed. On 2026-09-14 that printed
    #     :8294 is held by pid 41580 that is not a Living Room ('')
    # about the loop's OWN board, started by the loop eleven minutes earlier. A guard that cannot see
    # does not fail safe, it fails shut. PowerShell's CIM query is the supported replacement.
    try:
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
            capture_output=True, text=True, timeout=25, creationflags=NO_WINDOW).stdout
        return ps.strip()
    except Exception:
        return ""


def _kill_tree(pid: int) -> None:
    """The house kill rule: only THIS pid (captured by us), the whole tree so no spawn-worker outlives it."""
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=30,
                       creationflags=NO_WINDOW)
    except Exception:
        pass


# The only processes this loop is ever allowed to kill, by what their command line says they are.
# `pick-server.mjs` was missing until 2026-09-14, and this function is what the loop hands to
# SimBoard.start() — so the board's port could never be freed by design, only by accident.
OURS = ("run.py", "pick-server.mjs")

# Ports that belong to John. Never killed, whatever a command line claims, whatever is passed in.
JOHNS_PORTS = (8000, 8194, 8196, 5173, 8188, 8190, 8183, 8191)


def free_sim_port(port: int, wait_s: float = 30) -> bool:
    """Free :port if one of OUR processes still holds it — a Living Room or a sim Pick Board from an
    earlier run, or a spawn-worker that outlived its parent. Anything else is never killed, and
    John's own ports are never touched even if something of ours is sitting on one. Re-checks after."""
    if int(port) in JOHNS_PORTS:
        log(f":{port} is one of John's own ports — this loop does not kill anything there")
        return False
    pid = _port_owner(port)
    if pid is None:
        return True
    cmd = _cmdline(pid)
    if not any(marker in cmd for marker in OURS):
        log(f":{port} is held by pid {pid} which is not ours ({cmd[:120]!r}) — leaving it alone")
        return False
    log(f":{port} is held by a stale {'Living Room' if 'run.py' in cmd else 'sim Pick Board'} "
        f"(pid {pid}) — killing its tree")
    _kill_tree(pid)
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if _port_owner(port) is None:
            return True
        time.sleep(2)
    log(f":{port} STILL held after the kill — refusing to play against a process this loop cannot restart")
    return False


def gpu_used_mb() -> int | None:
    """What the 4090 holds right now (nvidia-smi), or None when it cannot be read."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             creationflags=NO_WINDOW,
                             capture_output=True, text=True, timeout=20).stdout.strip().splitlines()
        return int(out[0]) if out else None
    except Exception:
        return None


# 2026-09-14: was 8000, which is below what Sam's OWN eyes weigh (qwen3-vl:8b sits at ~10 GB) —
# so the moment he looked at a picture he locked himself out of the next round. The number has to
# mean "SOMEBODY ELSE has a real job on the card": a Hunyuan3D mesh or a Hunyuan 2.1 paint runs
# 16-20 GB, the Night Shift's QLoRA more. 18 GB sits above Sam's own footprint and below anyone
# else's, which is the only place it was ever supposed to sit.
GPU_BUSY_MB = int(os.getenv("SAM_GPU_BUSY_MB", "18000"))


def wait_for_gpu(max_wait_s: float = 3600, *, needed: bool = True) -> None:
    """Never start FACTORY work onto a busy 4090 — the Night Shift's training or a paint would spill to
    system memory and crawl. An outage is a wait.

    2026-09-14: `needed` is what stopped this gate from eating the night. It was written when a round
    loaded V17's architect locally (qwen3.8:27b, ~18 GB). The architect and every one of Sam's lanes
    are cloud now, so a --factory-off round asks the card for nothing but the eyes — and the eyes are
    Sam's own 10 GB model, which put the reading OVER the 8 GB threshold and made Sam queue behind
    himself, five minutes at a time, for a card nobody else wanted. A gate that blocks a job on that
    job's own footprint is not a gate, it is a deadlock."""
    if not needed:
        log("no factory work this round — the 4090 is not needed, so the GPU gate is skipped")
        return
    t0 = time.time()
    while time.time() - t0 < max_wait_s:
        used = gpu_used_mb()
        if used is None or used < GPU_BUSY_MB:
            return
        log(f"GPU busy ({used} MB in use, threshold {GPU_BUSY_MB}) — waiting 5 minutes before the round")
        heartbeat(phase=f"waiting for the GPU ({used} MB in use)")
        time.sleep(300)
    log("GPU still busy after an hour — playing anyway (the architect may crawl; nothing crashes, the card just times out)")


class SimLivingRoom:
    """The loop's own Living Room on :8001 — same code, its own event log, its own process we hold."""

    def __init__(self, port: int = SIM_PORT, repo: Path = common.ROOT):
        self.port, self.repo, self.proc = port, repo, None
        self.url = f"http://127.0.0.1:{port}"

    def up(self) -> bool:
        return _up(self.url + "/api/v17/pipeline")

    def start(self, wait_s: float = 120) -> bool:
        if self.proc is not None and self.proc.poll() is None and self.up():
            return True
        if self.up() and self.proc is None:
            # a stale instance from an earlier run (or a worker that outlived its parent). Never play against it —
            # a patch would never be proven and stale servers would pile up. Free the port or refuse.
            if not free_sim_port(self.port):
                return False
        env = dict(os.environ)
        env["V17_PORT"] = str(self.port)
        env["V17_EVENT_LOG"] = str(EVENTS_SIM)
        env["PICKBOARD"] = common.PICKBOARD          # its walls hang on Sam's board, never John's
        # 2026-09-14, John: "sam can use any cloud lane to train himself faster and better and more
        # accurate." The architect writes the plan on Sam's FIRST sentence, so its speed IS the
        # round's speed: measured on the same sentence, qwen3.8:27b on the 4090 took 70 s and
        # answered in paragraphs, gpt-oss:120b-cloud took 4.3 s and answered in short parts
        # (decision 32). John's own :8000 has been on the cloud tag since 09-11; the sim was still
        # on the local one, which is both the slow half and the 18 GB that jammed the GPU gate.
        # This env dict is a private copy handed to _spawn, so John's :8000 is untouched.
        env["V17_ARCHITECT_MODEL"] = os.getenv("SAM_ARCHITECT_MODEL", "gpt-oss:120b-cloud")
        py = living_room_python()
        if py is None:
            return False                        # the caller waits and retries; the log says why
        log(f"starting the sim Living Room on :{self.port} (events -> {EVENTS_SIM.name})")
        self.proc = _spawn([py, "run.py"], cwd=self.repo, env=env)
        if self.proc is None:
            return False
        ok = _wait(self.url + "/api/v17/pipeline", wait_s, f"the sim Living Room :{self.port}")
        return ok and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc is None:
            return
        log("stopping the sim Living Room")
        try:
            self.proc.terminate()
            self.proc.wait(timeout=20)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        pid = self.proc.pid
        self.proc = None
        _kill_tree(pid)                                       # children too: uvicorn spawn-workers outlive their parent
        t0 = time.time()
        while self.up() and time.time() - t0 < 30:          # the port must actually free — a port answering is not a restart
            time.sleep(2)
        if self.up():
            log(f"WARNING: :{self.port} still answers after stop — trying to free it by its owner pid")
            free_sim_port(self.port)

    def restart(self) -> bool:
        self.stop()
        return self.start()


# ── one round ─────────────────────────────────────────────────────────────────────────────────
def route_gaps(gap_ids: list[str], *, live: bool) -> dict:
    """Depth B/C: hand this round's new gaps to the gap router (node). Dry by default; --live pushes 'thing' jobs."""
    if not gap_ids or not common.GAP_ROUTER.exists() or not shutil.which("node"):
        return {"ran": False, "why": "no gaps" if not gap_ids else "gap-router.mjs or node not found"}
    cmd = ["node", str(common.GAP_ROUTER)] + (["--live"] if live else [])
    env = dict(os.environ, PICKBOARD=common.PICKBOARD)   # prop jobs land in the SIM's job bay
    try:
        r = subprocess.run(cmd, cwd=str(common.GAP_ROUTER.parent), capture_output=True, text=True, timeout=600,
                           creationflags=DETACHED, env=env)
        return {"ran": True, "live": live, "rc": r.returncode, "tail": (r.stdout or "")[-800:], "err": (r.stderr or "")[-400:]}
    except Exception as e:
        return {"ran": False, "why": f"{type(e).__name__}: {e}"}


def _house_line(world) -> str | None:
    """One short sentence naming the house Sam ended the night with, so tomorrow he builds a different
    one. From the world manifest — the app's own truth, never the model's memory of it."""
    man = world.manifest(common.SIM_SLUG) or {}
    brief = man.get("brief") if isinstance(man.get("brief"), dict) else None
    houses = (brief or {}).get("houses") if isinstance((brief or {}).get("houses"), list) else None
    if not houses:
        return None
    h = houses[0] if isinstance(houses[0], dict) else {}
    bits = [str(h.get(k)) for k in ("style", "stories", "roof") if h.get(k)]
    return ", ".join(bits)[:120] or None


WORLD_SHOTS = common.RUNS / "world-shots"


def snap_world(rid: str, started: float) -> None:
    """Keep a picture of the world at the end of every round.

    2026-09-14, John chose "snap it every round" for THE LINE's ASKED vs BUILT card. The builder
    writes ONE thumbnail and overwrites it in place, so without this there is no history: the card
    could only ever show the world as it is now, which answers a different question than "was the
    thing I asked for at 08:41 standing at 08:44".

    It does NOT re-render - the loop has no renderer, and pretending otherwise would put a stale
    picture under a fresh timestamp, which is worse than no picture. It copies what the builder
    last wrote and records, honestly, whether the world actually changed during this round. The
    card reads that flag and says "the world has not been rebuilt since 08:41" when it has not.

    Never fatal: a round must never fail over a screenshot.
    """
    try:
        d = common.WORLDS / common.SIM_SLUG / "output" / "world"
        shot = next(iter(sorted(d.glob("*thumbnail*.png"))), None) if d.is_dir() else None
        if shot is None:
            return
        WORLD_SHOTS.mkdir(parents=True, exist_ok=True)
        src_m = shot.stat().st_mtime
        name = f"{int(time.time())}.png"
        (WORLD_SHOTS / name).write_bytes(shot.read_bytes())
        common.capture(WORLD_SHOTS / "index.jsonl", {
            "shot": name, "taken": time.time(), "round": rid,
            "world_mtime": src_m, "rebuilt_this_round": src_m >= started,
            "source": str(shot),
        })
        for old in sorted(WORLD_SHOTS.glob("*.png"))[:-60]:      # keep the last sixty, quietly
            try:
                old.unlink()
            except OSError:
                pass
    except Exception as exc:                                     # a screenshot never fails a round
        log(f"world snapshot skipped: {type(exc).__name__}: {exc}")


def one_round(lr: SimLivingRoom, *, depth: str, max_turns: int, minutes: float, model: str | None, factory: bool = False) -> dict:
    rid = time.strftime("%Y%m%d-%H%M%S")
    round_started = time.time()            # so the world snapshot can say whether anything was rebuilt
    rd = common.RUNS / rid
    rd.mkdir(parents=True, exist_ok=True)
    heartbeat(round=rid, phase="seeding")
    seeded = seed_world.seed(common.WORLDS)
    if seeded.get("seeded"):
        log(f"seeded {seeded['slug']} from {seeded['from']}")
    reset = seed_world.reset(common.WORLDS, keep_manifests_to=rd / "world-kept")
    if reset["dropped"]:
        log(f"reset {reset['slug']}: dropped {len(reset['dropped'])} files from earlier rounds")
    world = sam.World(common.WORLDS)
    (rd / "world-before.json").write_text(json.dumps(world.manifest(common.SIM_SLUG) or {}, ensure_ascii=False)[:200000], encoding="utf-8")

    heartbeat(round=rid, phase="playing")
    mem = remember.load(sam_head())
    if mem.get("nights"):
        log(f"Sam has played {mem['nights']} nights before: has {len(remember.already_have(mem))} things, "
            f"still chasing {len(remember.still_chasing(mem))}, gave up on {len(remember.gave_up_on(mem))}")
    final = sam.play_round(rd, v17=sam.V17(lr.url), world=world, max_turns=max_turns, minutes=minutes,
                           model=model, mem=mem)
    (rd / "world-after.json").write_text(json.dumps(world.manifest(common.SIM_SLUG) or {}, ensure_ascii=False)[:200000], encoding="utf-8")
    snap_world(rid, round_started)
    log(f"round {rid}: {final['reason_ended']} after {final['turns']} turns, world v{final['world_version_start']} -> v{final['world_version_end']}")

    heartbeat(round=rid, phase="analyzing")
    an = analysis.analyze(rd)
    # what he got is the analyzer's verdict, not his hope: "got" is the only one that counts as having it.
    got = [w.get("text") or "" for w in an.get("wishes", []) if w.get("verdict") == "got"]
    mem = remember.remember_round(mem, things=final.get("things_asked_for") or [], got=got,
                                  rooms=final.get("rooms_visited") or [],
                                  house=_house_line(world))
    remember.save(sam_head(), mem)
    c = an.get("counts", {})
    log(f"round {rid}: {c.get('wishes', 0)} wishes, {len(an.get('defects', []))} defects, {len(an.get('gaps_filed', []))} gaps filed, judge {an.get('judge_status')}")

    routed = {"ran": False, "why": "depth A"}
    if depth in ("B", "C") and an.get("gaps_filed"):
        # --factory pushes "thing" jobs to the board (renders, meshes and paints on the 4090 — the heaviest
        # thing this loop can start). Without it the router still decides and drafts cards, dry.
        heartbeat(round=rid, phase="routing gaps" + (" (live)" if factory else " (dry)"))
        routed = route_gaps(an["gaps_filed"][:MAX_GAPS_ROUTED], live=factory)
        log(f"gap router ({'live' if factory else 'dry'}): {routed}")

    mech = {"patched": False, "why": "depth " + depth}
    if depth == "C" and an.get("defects"):
        heartbeat(round=rid, phase="mechanic")
        mech = mechanic.run(rd, common.ROOT)
        log(f"mechanic: patched={mech.get('patched')} gate={mech.get('gate')} why={mech.get('why')} files={mech.get('files')}")
        if mech.get("patched") and mech.get("restart_needed", True):
            heartbeat(round=rid, phase="restarting the sim Living Room after a patch")
            lr.restart()
    summary = {"round": rid, "final": final, "counts": c, "defects": len(an.get("defects", [])), "gaps": an.get("gaps_filed", []),
               "router": routed, "mechanic": mech, "at": common.now_iso()}
    common.capture(common.RUNS / "rounds.jsonl", summary)
    return summary


def main() -> int:
    common.utf8_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1000)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--depth", choices=["A", "B", "C"], default="C")
    ap.add_argument("--max-turns", type=int, default=14)
    ap.add_argument("--minutes", type=float, default=35)
    ap.add_argument("--model", default=None)
    ap.add_argument("--factory", action="store_true", help="at depth B/C, push Sam's unmet things to the factory (GPU work); default: decide only")
    # 2026-09-14, John: "make the loops shorter like 20 runs before consolidation and learning and
    # before moving on to the next 20, this should accelerate the learning." Twenty nights is the
    # smallest run where the SHAPE of Sam's play is visible - which wishes were refused the same way
    # every time, which door each thing went out of - and it is about an hour, so the training
    # corpus is never more than an hour behind. --batch 0 turns it off and the loop runs as before.
    ap.add_argument("--batch", type=int, default=20,
                    help="consolidate and learn every N rounds (0 = never)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    rounds = 1 if a.once else a.rounds
    depth = a.depth
    common.RUNS.mkdir(parents=True, exist_ok=True)
    if STOP.exists():
        STOP.unlink()
    log(f"Sam Loop start: rounds={rounds} depth={depth} factory={a.factory} turns={a.max_turns} minutes={a.minutes} runs={common.RUNS}")
    lr = SimLivingRoom()
    board = sim_board.SimBoard()
    played = 0
    batch = batch_size(a.batch)             # --batch is where it starts; loop-control.json steers it
    since_batch, batches = 0, 0
    if batch != a.batch:
        log(f"loop-control.json says batch={batch} (--batch was {a.batch})")
    try:
        for i in range(rounds):
            if STOP.exists():
                log("STOP file found — ending between rounds"); break
            asked = batch_size(batch)
            if asked != batch:
                log(f"batch size changed: every {batch} rounds -> "
                    + (f"every {asked} rounds" if asked else "never (consolidation off)"))
                batch = asked
            wait_if_paused()
            heartbeat(phase="dependencies", round_index=i)
            if not ensure_ollama():
                log("Ollama not available — waiting 5 minutes"); time.sleep(300); continue
            if not board.start(free_port=free_sim_port):
                log("the sim Pick Board did not come up — waiting 5 minutes"); time.sleep(300); continue
            if not ensure_bat_service(common.BUILDER + "/api/health", BUILDER_BAT, "the Neighbourhood Builder :8196", 180):
                log("Builder not available — waiting 5 minutes"); time.sleep(300); continue
            wait_for_gpu(needed=a.factory)
            if not lr.start():
                if living_room_python() is None:
                    log("STOPPING: there is no python here that can run the Living Room, so no round "
                        "will ever play. Install uvicorn, or start the loop with the python that has it.")
                    heartbeat(phase="stopped", rounds_played=played, error="no python can import uvicorn")
                    break
                log("the sim Living Room did not come up — waiting 2 minutes"); time.sleep(120); continue
            try:
                one_round(lr, depth=depth, max_turns=a.max_turns, minutes=a.minutes, model=a.model, factory=a.factory)
                played += 1
                # THE BATCH BOUNDARY. Read the last N nights, learn one thing from them, put it in
                # Sam's head, and rebuild the training corpus. It never raises: a batch that cannot
                # reach a model still files its data, and Sam starts the next twenty with the head
                # he already had.
                # `since_batch` counts rounds since the last consolidation rather than dividing the
                # total, so changing the dial mid-run does exactly what it looks like it does: set it
                # to 10 after 7 rounds and the next batch lands 3 rounds later, not immediately and
                # not at some multiple of the old number.
                since_batch += 1
                if consolidate is not None and batch > 0 and since_batch >= batch:
                    batches += 1
                    heartbeat(phase=f"consolidating batch {batches}", round_index=i)
                    log(f"— batch {batches}: {since_batch} nights played, consolidating —")
                    rounds_in_batch, since_batch = since_batch, 0
                    try:
                        consolidate.consolidate(common.RUNS, batch_no=batches, rounds=rounds_in_batch,
                                                head_path=sam_head(), log=log)
                    except Exception as e:      # noqa: BLE001
                        log(f"batch {batches}: consolidation failed, the loop carries on: {type(e).__name__}: {e}")
            except Exception as e:                      # a round must never kill the loop; the next one starts clean
                log(f"round failed: {type(e).__name__}: {e}")
                heartbeat(phase="round failed", error=str(e)[:300])
                time.sleep(30)
    finally:
        # A run that ends with "stopped" tells John nothing. End with what Sam WANTS - what he got,
        # what he is still chasing, and what he gave up on, which is the list the factory has never
        # been able to make. John, 2026-09-14: "he ends with what he wants."
        if consolidate is not None:
            try:
                consolidate.wants_report(sam_head(), common.RUNS, log=log)
            except Exception as e:      # noqa: BLE001 — the last line of a run never raises
                log(f"could not write what Sam wants: {type(e).__name__}: {e}")
        heartbeat(phase="stopped", rounds_played=played)
        if a.once:
            lr.stop()
        board.stop(free_port=free_sim_port)
        log(f"Sam Loop end: {played} rounds played")
    return 0


def selftest() -> int:
    """The pieces that do not need John's machine: pause windows, the STOP file, the heartbeat, a round against the fake app."""
    import tempfile
    from fake_living_room import FakeLivingRoom
    fails = []

    def check(name, ok, detail=""):
        print(("  ok   " if ok else "  FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
        if not ok:
            fails.append(name)

    global PAUSE_WINDOWS
    with tempfile.TemporaryDirectory() as td:
        PAUSE_WINDOWS = Path(td) / "pause-windows.txt"
        check("no pause file: not paused", in_pause_window() is False)
        PAUSE_WINDOWS.write_text("02:00-03:30\n# comment\n23:00-01:00\n")
        check("inside a window", in_pause_window(datetime(2026, 9, 10, 2, 15)) and in_pause_window(datetime(2026, 9, 10, 23, 59)) and in_pause_window(datetime(2026, 9, 10, 0, 30)))
        check("  trips: outside every window", not in_pause_window(datetime(2026, 9, 10, 12, 0)) and not in_pause_window(datetime(2026, 9, 10, 3, 30)))
        # a whole round through one_round() against the fake app, depth A, scripted Sam
        worlds = Path(td) / "worlds"
        fake = FakeLivingRoom(worlds, slug="sim-neighborhood")
        home = worlds / "mr-johns-neighborhood" / "output" / "world"; home.mkdir(parents=True)
        (home / "9-world.json").write_text(json.dumps({"slug": "mr-johns-neighborhood", "brief": {"houses": [1, 2, 3, 4]}}))
        fake.start()
        old = (common.WORLDS, common.RUNS, common.GAP_LEDGER)
        try:
            common.WORLDS = worlds; common.RUNS = Path(td) / "runs"; common.GAP_LEDGER = Path(td) / "gaps.jsonl"
            script = iter([
                {"i_see": "grass", "i_type": "I want a house right here with a big porch", "pick": None, "card": None, "done": False, "didnt_get": []},
                {"i_see": "grass", "i_type": "two", "pick": None, "card": None, "done": False, "didnt_get": []},
                {"i_see": "grass", "i_type": "build it", "pick": None, "card": None, "done": False, "didnt_get": []},
                {"i_see": "a plan", "i_type": "build it", "pick": None, "card": "build", "done": False, "didnt_get": []},
                {"i_see": "pictures", "i_type": "the first one", "pick": {"tag": "c1", "why": "nice"}, "card": None, "done": False, "didnt_get": []},
                {"i_see": "a house!", "i_type": "I'm proud of it", "pick": None, "card": None, "done": True, "didnt_get": []},
            ])
            orig = sam.play_round

            def scripted(rd, **kw):
                kw["ask"] = lambda s, m, sc: next(script); kw["poll_s"] = 0.2; kw["build_wait_s"] = 20; kw["wall_wait_s"] = 20
                kw["board"] = sam.Board(fake.url); kw["model"] = "fake"
                return orig(rd, **kw)
            sam.play_round = scripted

            class LR:  # a stand-in for SimLivingRoom pointing at the fake
                url = fake.url
                def restart(self): return True
            an_ask = lambda s, m, sc: {"verdicts": []}
            orig_an = analysis.analyze
            analysis.analyze = lambda rd, **kw: orig_an(rd, ask=an_ask, ledger=common.GAP_LEDGER)
            s = one_round(LR(), depth="A", max_turns=8, minutes=3, model="fake")
            check("one_round played to 'proud' and the sim world moved 0 -> 1", s["final"]["reason_ended"] == "proud" and s["final"]["world_version_end"] == 1, str(s["final"]))
            rd = common.RUNS / s["round"]
            check("the round folder holds transcript, analysis, report, world before/after", all((rd / f).exists() for f in ("transcript.jsonl", "analysis.json", "REPORT.md", "world-before.json", "world-after.json")))
            check("rounds.jsonl has the summary and the heartbeat says analyzing/playing happened", (common.RUNS / "rounds.jsonl").exists() and json.loads((common.RUNS / "heartbeat.json").read_text())["round"] == s["round"])
            check("depth A never runs the router or the mechanic", s["router"]["ran"] is False and s["mechanic"]["patched"] is False)
            check("the home world was never written", sorted(f.name for f in home.iterdir()) == ["9-world.json"])
        finally:
            fake.stop()
            common.WORLDS, common.RUNS, common.GAP_LEDGER = old
            sam.play_round = orig
            analysis.analyze = orig_an

    # THE DIAL. The only thing that matters here is that a bad value can never stop the night, and
    # that a good one takes effect without a restart.
    global CONTROL
    _saved = CONTROL
    try:
        with tempfile.TemporaryDirectory() as td:
            CONTROL = Path(td) / "loop-control.json"
            check("with no control file, the dial stays where it was", batch_size(20) == 20)
            check("a written dial is read back", set_batch(10) == 10 and batch_size(20) == 10)
            check("zero is a real setting: keep playing, never consolidate", set_batch(0) == 0 and batch_size(20) == 0)
            CONTROL.write_text("{not json", encoding="utf-8")
            check("a broken control file leaves the dial alone", batch_size(20) == 20)
            CONTROL.write_text('{"batch": "ten"}', encoding="utf-8")
            check("a dial that is not a number leaves it alone", batch_size(20) == 20)
            CONTROL.write_text('{"batch": true}', encoding="utf-8")
            check("true is not 1 — a boolean leaves it alone", batch_size(20) == 20)
            CONTROL.write_text('{"batch": -5}', encoding="utf-8")
            check("a negative dial leaves it alone", batch_size(20) == 20)
            CONTROL.write_text('{"batch": 99999}', encoding="utf-8")
            check("a silly-large dial leaves it alone", batch_size(20) == 20)
            check("set_batch clamps rather than refusing", set_batch(99999) == BATCH_MAX and set_batch(-3) == 0)
    finally:
        CONTROL = _saved

    print(f"\n{'ALL GREEN' if not fails else 'FAILED: ' + ', '.join(fails)} — {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
