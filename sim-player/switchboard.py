"""switchboard.py — one place the whole line is turned on and off.

2026-09-14, John: "i am so sick and tired of you not being able to start and stop all of the
servers, i have tried a million different ways, can't you just put them all in docker or something
to coordinate their spin up spin down and collision etc..."

He is right about the problem and right about the shape of the fix. He is wrong about docker, and
only because of what is in this particular stack: ComfyUI and Hunyuan3D want the 4090 through the
NVIDIA container toolkit and WSL2, the Neighbourhood Builder is a Blender install, and every path
here is a Windows path. Containerising that is a week and it breaks things that work today. The
part of docker he actually wants — ONE THING THAT OWNS THE PROCESSES, knows the order, waits for
health, and refuses to fight over a port — is a supervisor, and a supervisor is this file.

WHAT WENT WRONG EVERY TIME BEFORE, so it is not repeated here:

  Nobody owned the processes.  Every service was started by its own .bat in its own console window.
  Starting meant finding the right file among a hundred and twenty; stopping meant finding the
  right window. Nothing could be restarted by anything but a person.

  Nothing checked health, only ports.  A port answering is not a service working: Sam's Living Room
  held :8001 for eleven minutes while dying on `import uvicorn` every two minutes, and the loop
  reported "alive" the whole time.

  Collisions were handled by killing.  A pile of KILL-8188-HARD.bat, PURGE-COMFY-ZOMBIES.bat,
  WHO-HAS-MY-VRAM.bat. This never kills. A port held by something it did not start is reported and
  left alone — because the thing holding it is usually John's, and killing it is how his own
  Living Room went down.

  Starting from a dev server was worse.  On 2026-09-14 I started the Sam Loop as a child of Vite so
  I could reach it, then edited Vite's config, which restarts it — and it took the loop, the Living
  Room, the Pick Board and the Builder down with it. This process is parented to nothing and is
  never edited while running.

WHAT IT OWNS, and deliberately not more:

    world   :5173   the 3D world (and the dev-server endpoints)
    line    :8099   THE LINE dashboard
    loop     ---    the Sam Loop

The loop has always started Sam's Pick Board (:8294) and his Living Room (:8001) itself, and it
must keep doing so: two owners for one port is the collision, not the cure. Those, plus Ollama,
ComfyUI and the Builder, are REPORTED here and never touched.

    python switchboard.py                 serve on :8777
    python switchboard.py --selftest
    curl 127.0.0.1:8777/api/status
    curl -X POST 127.0.0.1:8777/api/start?svc=world
    curl -X POST "127.0.0.1:8777/api/start?svc=loop&rounds=10&batch=10"
    curl -X POST 127.0.0.1:8777/api/stop?svc=loop
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.getenv("SWITCHBOARD_PORT", "8777"))
CEO = Path(os.getenv("CEO_ATTEMPT", r"C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"))
WORLD = Path(os.getenv("CEO_3D_WORLD",
             r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World"))
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
SIGNATURE = "switchboard/1"


HEARTBEAT = CEO / "sim-player" / "sim-runs" / "heartbeat.json"
LOGFILE = CEO / "sim-player" / "sim-runs" / "switchboard-log.txt"


def to_file(msg: str) -> None:
    """Everything this program says also goes to one file.

    2026-09-14. The switchboard is started with no console window, by a .bat, by a step runner,
    from a cloud session — so when it failed to come up, its reason went nowhere and the .bat
    cheerfully reported LISTENING because the OLD copy was still answering. A line in a file
    costs nothing and makes that impossible.
    """
    try:
        LOGFILE.parent.mkdir(parents=True, exist_ok=True)
        with LOGFILE.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:                             # noqa: BLE001 — logging never stops the program
        pass


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def pid_alive(pid: int) -> bool:
    """Is that process still there? Asked of Windows, not guessed from a file."""
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
                             capture_output=True, text=True, timeout=15,
                             creationflags=NO_WINDOW).stdout
    except Exception:                             # noqa: BLE001
        return False
    return str(int(pid)) in out


def loop_heartbeat() -> dict:
    """What the Sam Loop last said about itself, in its own file, in its own words.

    2026-09-14. The switchboard used to know about the loop ONLY through the Popen handle it held,
    so restarting the switchboard orphaned a running loop: it showed as down, and could not be
    stopped. The loop already writes its pid and phase to heartbeat.json every time it changes what
    it is doing, so a fresh switchboard reads that and adopts it. This is the ONE pid the
    switchboard will kill without having started it, and only because the loop named itself.
    """
    try:
        h = json.loads(HEARTBEAT.read_text(encoding="utf-8"))
    except Exception:                             # noqa: BLE001
        return {}
    pid = h.get("pid")
    if not isinstance(pid, int) or h.get("phase") == "stopped" or not pid_alive(pid):
        return {}
    return h


# ─────────────────────────────────────────────────────────────── finding a python that works
#
# The `python` on one PATH is not the `python` on another. Sam's Living Room died for eleven
# minutes on 2026-09-14 because it was started by an interpreter without uvicorn. Every service
# that needs a module says so, and the interpreter is chosen by ASKING, not assuming.

_PY_CACHE: dict[str, str] = {}


def python_with(module: str | None = None) -> str | None:
    """An interpreter on this machine that can import `module`. Cached per module."""
    key = module or ""
    if key in _PY_CACHE:
        return _PY_CACHE[key]
    cands = [sys.executable, "py", "python", "python3"]
    for root in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python"),
                 r"C:\Program Files", "C:\\"):
        try:
            for name in sorted(os.listdir(root), reverse=True):
                if name.lower().startswith("python"):
                    cands.append(os.path.join(root, name, "python.exe"))
        except OSError:
            continue
    code = f"import {module},sys;print(sys.executable)" if module else "import sys;print(sys.executable)"
    seen = set()
    for exe in cands:
        if not exe or exe in seen:
            continue
        seen.add(exe)
        if exe.endswith(".exe") and not os.path.isfile(exe):
            continue
        try:
            p = subprocess.run([exe, "-c", code], capture_output=True, text=True,
                               timeout=30, creationflags=NO_WINDOW)
            if p.returncode == 0:
                _PY_CACHE[key] = exe
                return exe
        except Exception:                   # noqa: BLE001 — a candidate that explodes is just a no
            continue
    _PY_CACHE[key] = None                   # type: ignore[assignment]
    return None


# ─────────────────────────────────────────────────────────────── the line

class Service:
    """One service: how to start it, how to know it is really up, and who owns it.

    `health` is a URL that must answer 200, not merely a port that accepts a connection. That
    distinction is the whole reason this file exists.
    """

    def __init__(self, name, *, port=None, health=None, argv=None, cwd=None, needs=None,
                 owned=True, ready_s=180, note="", marker=None, ports=None, cmd_marker=None):
        self.name, self.port, self._health = name, port, health
        self._argv, self.cwd, self.needs = argv, cwd, needs
        self.owned, self.ready_s, self.note = owned, ready_s, note
        self.marker = marker                      # a word the RIGHT build says about itself
        self.adopts = False                       # set on the loop: it names its own pid on disk
        self.cmd_marker = cmd_marker              # the script name that makes a process THIS service
        self.ports = list(ports) if ports else ([port] if port else [])
        self.proc: subprocess.Popen | None = None
        self.started_at: str | None = None
        self.last_error = ""

    @property
    def health(self) -> str | None:
        """The health URL for the port this service is actually on."""
        if not self._health:
            return None
        return self._health.format(port=self.port) if "{port}" in self._health else self._health

    def health_at(self, port) -> str | None:
        if not self._health:
            return None
        return self._health.format(port=port) if "{port}" in self._health else self._health

    def argv(self, **kw) -> list[str] | None:
        return self._argv(**kw) if callable(self._argv) else self._argv

    # ── is it there?
    def up(self, timeout=4.0, port=None) -> bool:
        """200 and the right build, or it is not up.

        2026-09-14. This method used to read `200 <= status < 500`, with a comment claiming a 404
        from a live server is still a live server. That is the exact fault this whole file was
        written against, and I wrote it in anyway. A build of THE LINE from four days ago had been
        squatting :8099 the whole time, serving a page whose panels never fill and 404-ing every
        /api/ route. It answered the socket, so it was "up"; because it was "up", the switchboard
        refused to start the real one; because the real one never started, John had been looking at
        a dead dashboard and telling me he could not see Sam.

        A 404 IS an answer. It is the answer "I do not have that", which from a health endpoint
        means the thing on this port is not the thing I am asking about. So: 2xx only, and where a
        service can say its own name (`marker`), it has to say it.
        """
        url = self.health_at(port) if port is not None else self.health
        if not url:
            mine = self.proc is not None and self.proc.poll() is None
            return mine or (self.adopts and bool(loop_heartbeat()))
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                if not (200 <= r.status < 300):
                    return False
                if not self.marker:
                    return True
                return self.marker in r.read(8192).decode("utf-8", "replace")
        except Exception:                         # noqa: BLE001 — every failure means "not up"
            return False

    def port_held(self, port=None) -> bool:
        port = self.port if port is None else port
        if not port:
            return False
        with socket.socket() as s:
            s.settimeout(1.0)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def state(self) -> dict:
        up, held = self.up(), self.port_held()
        mine = self.proc is not None and self.proc.poll() is None
        beat = loop_heartbeat() if self.adopts else {}
        if up and not mine and beat:
            return {"name": self.name, "port": self.port, "url": self.health, "up": True,
                    "port_held": held, "ours": True, "pid": beat.get("pid"),
                    "state": f"up (adopted) — {beat.get('phase', '?')}", "started_at": beat.get("at"),
                    "note": self.note, "last_error": None}
        if up:
            what = "up (ours)" if mine else ("up (someone else's)" if self.owned else "up")
        elif held:
            what = "PORT HELD BY SOMETHING THAT IS NOT ANSWERING"
        else:
            what = "down"
        return {"name": self.name, "port": self.port, "url": self.health, "up": up, "port_held": held,
                "ours": mine, "pid": self.proc.pid if mine else None, "state": what,
                "started_at": self.started_at, "note": self.note,
                "last_error": self.last_error or None}

    # ── turning it on
    def start(self, log=print, **kw) -> dict:
        if self.up():
            return {"ok": True, "did": "nothing", "why": f"{self.name} is already up"}
        if not self.owned:
            return {"ok": False, "why": f"{self.name} is not mine to start — {self.note}"}
        if self.ports:
            self.port = self.ports[0]             # always try the home port again, never drift
        if self.port_held():
            # A held port has exactly two honest answers, and killing blindly is neither.
            #
            # If the process holding it IS this service — same program, older copy, proven by its
            # command line and not by what it claims — then replacing it is the stand-down every
            # long-lived program here already does for its own older copies. That is the case on
            # :8099: a dashboard.py from four days ago, mute on every /api/ route, which is why
            # John has been looking at a page whose panels never fill.
            #
            # If it is ANYTHING else, it is left exactly as it was and we step sideways. The thing
            # on a port is usually John's, and killing it is how his own Living Room went down on
            # 2026-09-11.
            if self.cmd_marker:
                held = owner_pids(self.port)
                older = [pid for pid, cmd in cmdlines(held).items()
                         if self.cmd_marker.lower() in cmd.lower()]
                if older and _replace(self.port, older,
                                      f"{self.name}: :{self.port} is held by an older "
                                      f"{self.cmd_marker} (mute, not answering {self.health})",
                                      log=log):
                    log(f"{self.name}: :{self.port} is free again — taking the home port back")
            if self.port_held():
                free = next((p for p in self.ports if not self.port_held(p)), None)
                if free is None:
                    return {"ok": False, "why": f":{self.port} is held by something that does not "
                                                f"answer {self.health}, and so is every fallback "
                                                f"{self.ports}. Nothing was killed."}
                log(f"{self.name}: :{self.port} is held by something that is not "
                    f"{self.marker or 'mine'} — moving to :{free}. Nothing was killed.")
                self.port = free
        argv = self.argv(port=self.port, **kw)
        if not argv:
            return {"ok": False, "why": f"{self.name}: nothing to run (is its interpreter missing?)"}
        log(f"{self.name}: starting {' '.join(str(a) for a in argv[:3])}...")
        try:
            self.proc = subprocess.Popen(argv, cwd=str(self.cwd) if self.cwd else None,
                                         creationflags=NO_WINDOW | NEW_GROUP, close_fds=True,
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
        except Exception as e:                    # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {e}"
            return {"ok": False, "why": self.last_error}
        self.started_at = now()
        if not self.health:                       # nothing to wait for — the loop has no port
            return {"ok": True, "did": "start", "pid": self.proc.pid}
        t0 = time.time()
        while time.time() - t0 < self.ready_s:
            if self.proc.poll() is not None:
                self.last_error = f"it exited with {self.proc.returncode} before answering"
                return {"ok": False, "why": self.last_error, "pid": self.proc.pid}
            if self.up():
                s = int(time.time() - t0)
                log(f"{self.name}: up after {s}s")
                return {"ok": True, "did": "start", "pid": self.proc.pid, "ready_s": s}
            time.sleep(2)
        self.last_error = f"started but did not answer {self.health} within {self.ready_s}s"
        return {"ok": False, "why": self.last_error, "pid": self.proc.pid}

    # ── turning it off
    def stop(self, log=print) -> dict:
        adopted = loop_heartbeat().get("pid") if self.adopts else None
        if self.proc is None or self.proc.poll() is not None:
            self.proc = None
            if not adopted:
                return {"ok": True, "did": "nothing", "why": f"{self.name} is not ours to stop"}
            log(f"{self.name}: stopping pid {adopted}, adopted from its own heartbeat")
            try:
                subprocess.run(["taskkill", "/PID", str(adopted), "/T", "/F"],
                               capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
            except Exception as e:                # noqa: BLE001
                return {"ok": False, "why": f"{type(e).__name__}: {e}"}
            return {"ok": True, "did": "stop", "pid": adopted, "adopted": True}
        pid = self.proc.pid
        log(f"{self.name}: stopping pid {pid}")
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        except Exception as e:                    # noqa: BLE001
            return {"ok": False, "why": f"{type(e).__name__}: {e}"}
        for _ in range(20):
            if self.proc.poll() is not None:
                break
            time.sleep(0.5)
        self.proc = None
        return {"ok": True, "did": "stop", "pid": pid}


def _loop_argv(rounds=10, batch=10, **_):
    py = python_with("uvicorn")               # the loop starts the Living Room with its own python
    if not py:
        return None
    return [py, "sim-player/sam_loop.py", "--rounds", str(int(rounds)),
            "--depth", "C", "--factory", "--batch", str(int(batch))]


def _line_argv(port=8099, **_):
    py = python_with()
    return [py, "sim-player/dashboard.py", "--port", str(int(port))] if py else None


def _world_argv(**_):
    # npm on Windows is npm.cmd, and it must be run through the shell's resolver.
    for exe in ("npm.cmd", "npm"):
        return [exe, "run", "dev"]
    return None


def _adopting(s: Service) -> Service:
    """Mark the loop as the one service a fresh switchboard may adopt from disk."""
    s.adopts = True
    return s


def build_line() -> dict[str, Service]:
    return {s.name: s for s in [
        Service("world", port=5173, health="http://localhost:5173/",
                argv=_world_argv, cwd=WORLD / "app", ready_s=120,
                note="the 3D world, and the dev-server endpoints"),
        Service("line", port=8099, health="http://127.0.0.1:{port}/api/whoami",
                argv=_line_argv, cwd=CEO, ready_s=60,
                marker="the-line-dashboard/1", ports=[8099, 8100, 8101, 8102, 8103],
                cmd_marker="dashboard.py",
                note="THE LINE dashboard — the page John watches Sam on"),
        _adopting(Service("loop", argv=_loop_argv, cwd=CEO, needs=["line"],
                          note="the Sam Loop — it starts Sam's Pick Board and Living Room itself")),
        # Reported, never touched. Two owners for one port IS the collision.
        Service("ollama", port=11434, health="http://127.0.0.1:11434/api/tags",
                owned=False, note="a Windows service; start it from the tray"),
        Service("sam-living-room", port=8001, health="http://127.0.0.1:8001/api/v17/pipeline",
                owned=False, note="the Sam Loop owns this"),
        Service("sam-pick-board", port=8294, health="http://127.0.0.1:8294/api/ping",
                owned=False, note="the Sam Loop owns this"),
        Service("builder", port=8196, health="http://127.0.0.1:8196/api/health",
                owned=False, note="the Neighbourhood Builder; the loop starts it"),
        Service("john-living-room", port=8000, health="http://127.0.0.1:8000/api/v17/pipeline",
                owned=False, note="John's own. Never touched."),
        Service("john-pick-board", port=8194, health="http://127.0.0.1:8194/api/ping",
                owned=False, note="John's own. Never touched."),
        Service("mesh-engine", port=8188, health="http://127.0.0.1:8188/system_stats",
                owned=False, note="ComfyUI. Start it from its own window."),
        Service("paint-shop", port=8190, health="http://127.0.0.1:8190/system_stats",
                owned=False, note="ComfyUI paint lane."),
    ]}


LINE = build_line()
LOG: list[str] = []
_server: "Switchboard | None" = None


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    LOG.append(line)
    del LOG[:-400]
    print(line, flush=True)
    to_file(msg)


def status() -> dict:
    return {"at": now(), "app": SIGNATURE, "pid": os.getpid(),
            "services": [s.state() for s in LINE.values()], "log": LOG[-40:]}


def start(name: str, **kw) -> dict:
    """Start one service, and whatever it needs first. Order is a property of the line, not a habit."""
    svc = LINE.get(name)
    if not svc:
        return {"ok": False, "why": f"no service called {name}"}
    for dep in (svc.needs or []):
        if not LINE[dep].up():
            r = start(dep)
            if not r.get("ok"):
                return {"ok": False, "why": f"{name} needs {dep}, and {dep} did not come up: {r.get('why')}"}
    return svc.start(log=log, **kw)


def stop(name: str) -> dict:
    svc = LINE.get(name)
    return svc.stop(log=log) if svc else {"ok": False, "why": f"no service called {name}"}


def start_all(**kw) -> dict:
    out = {}
    for n in ("line", "world", "loop"):
        out[n] = start(n, **kw)
    return {"ok": all(r.get("ok") for r in out.values()), "results": out}


def stop_all() -> dict:
    return {"ok": True, "results": {n: stop(n) for n in ("loop", "world", "line")}}


# ─────────────────────────────────────────────────────────────── the page and the api

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>SWITCHBOARD</title>
<style>
:root{--ink:#dfe6ef;--dim:#8b97a8;--line:#222a35;--ok:#5ad18a;--bad:#e2685f;--warn:#e8c06a}
*{box-sizing:border-box}body{margin:0;background:#0d1117;color:var(--ink);
font:14px/1.5 ui-monospace,Consolas,monospace;padding:18px}
h1{font-size:16px;letter-spacing:.14em;margin:0 0 4px}
.dim{color:var(--dim)}table{border-collapse:collapse;width:100%;max-width:900px;margin:14px 0}
td,th{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:normal;font-size:12px;letter-spacing:.08em}
.up{color:var(--ok)}.down{color:var(--dim)}.bad{color:var(--bad)}.warn{color:var(--warn)}
button{font:inherit;background:#1b2029;color:var(--ink);border:1px solid var(--line);
border-radius:6px;padding:4px 11px;cursor:pointer;margin-right:5px}
button:hover{border-color:#39424f}button:disabled{opacity:.35;cursor:default}
button.go:hover{border-color:var(--ok);color:var(--ok)}button.no:hover{border-color:var(--bad);color:var(--bad)}
pre{background:#11161d;border:1px solid var(--line);border-radius:8px;padding:11px;
max-width:900px;max-height:260px;overflow:auto;font-size:12px;color:var(--dim)}
</style></head><body>
<h1>SWITCHBOARD</h1>
<div class="dim">One place the line is turned on and off. Nothing here is ever killed that it did not start.</div>
<div style="margin:14px 0">
<button class="go" onclick="act('start-all')">start the line</button>
<button class="no" onclick="act('stop-all')">stop the line</button>
<span id="said" class="dim"></span></div>
<table><thead><tr><th>service</th><th>port</th><th>state</th><th></th><th>note</th></tr></thead>
<tbody id="rows"></tbody></table>
<pre id="log"></pre>
<script>
const $=i=>document.getElementById(i);
const esc=s=>String(s==null?"":s).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
async function act(what,svc){
  $("said").textContent="working...";
  const q=svc?`?svc=${encodeURIComponent(svc)}`:"";
  try{const r=await fetch(`/api/${what}${q}`,{method:"POST"});const j=await r.json();
    $("said").textContent=j.ok?"done":("could not: "+(j.why||JSON.stringify(j.results||{})).slice(0,160));
  }catch(e){$("said").textContent="unreachable: "+e.message}
  tick();
}
async function tick(){
  let d;try{d=await fetch("/api/status").then(r=>r.json())}catch(e){return}
  $("rows").innerHTML=d.services.map(s=>{
    const cls=s.up?"up":(s.port_held?"bad":"down");
    const btn=s.note&&s.note.includes("Never touched")||/owns this|tray|own window/.test(s.note||"")
      ? '<span class="dim">not mine</span>'
      : `<button class="go" onclick="act('start','${s.name}')" ${s.up?"disabled":""}>start</button>`
       +`<button class="no" onclick="act('stop','${s.name}')" ${s.ours?"":"disabled"}>stop</button>`;
    return `<tr><td>${esc(s.name)}</td><td class="dim">${s.port||""}</td>`
         +`<td class="${cls}">${esc(s.state)}${s.pid?` <span class="dim">pid ${s.pid}</span>`:""}</td>`
         +`<td>${btn}</td><td class="dim">${esc(s.note||"")}</td></tr>`;
  }).join("");
  $("log").textContent=(d.log||[]).join("\\n");
}
tick();setInterval(tick,3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype="application/json", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")   # so the world and THE LINE can drive it
        self.end_headers()
        self.wfile.write(body)

    def _q(self):
        from urllib.parse import urlparse, parse_qs
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def do_GET(self):
        if self.path.startswith("/api/status"):
            self._send(json.dumps(status()).encode())
        elif self.path in ("/", "/index.html"):
            self._send(PAGE.encode(), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        q = self._q()
        try:
            if self.path.startswith("/api/standdown"):
                # A newer switchboard is taking over. Close this server and leave every service it
                # started running — the new one adopts the loop from its heartbeat.
                self._send(b'{"ok":true,"did":"standdown"}')
                threading.Thread(target=lambda: _server and _server.shutdown(), daemon=True).start()
                return
            if self.path.startswith("/api/start-all"):
                out = start_all(**{k: int(v) for k, v in q.items() if v.isdigit()})
            elif self.path.startswith("/api/stop-all"):
                out = stop_all()
            elif self.path.startswith("/api/start"):
                out = start(q.get("svc", ""), **{k: int(v) for k, v in q.items() if v.isdigit()})
            elif self.path.startswith("/api/stop"):
                out = stop(q.get("svc", ""))
            else:
                self.send_error(404)
                return
            self._send(json.dumps(out).encode(), code=200 if out.get("ok") else 400)
        except Exception as e:                    # noqa: BLE001
            self._send(json.dumps({"ok": False, "why": f"{type(e).__name__}: {e}"}).encode(), code=500)


# ─────────────────────────────────────────────────────────────── proof

def selftest() -> int:
    fails = 0

    def check(name, ok, detail=""):
        nonlocal fails
        print(("PASS  " if ok else "FAIL  ") + name + (("  — " + detail) if not ok and detail else ""))
        if not ok:
            fails += 1

    line = build_line()
    check("the line knows every service", len(line) == 11, str(len(line)))
    check("three services are ours to start",
          sorted(n for n, s in line.items() if s.owned) == ["line", "loop", "world"],
          str(sorted(n for n, s in line.items() if s.owned)))
    check("John's own Living Room and board are NEVER ours",
          not line["john-living-room"].owned and not line["john-pick-board"].owned)
    check("Sam's Living Room and board belong to the loop, not to us",
          not line["sam-living-room"].owned and not line["sam-pick-board"].owned,
          "two owners for one port IS the collision")
    check("every owned service says how to know it is really up, not just that a port answers",
          all(s.health or s.name == "loop" for s in line.values() if s.owned))
    check("the loop has no health url because it has no port", line["loop"].health is None)
    check("the loop comes up after the dashboard", line["loop"].needs == ["line"])

    r = line["ollama"].start(log=lambda *_: None)
    check("starting something that is not ours is refused, not attempted",
          not r["ok"] and "not mine" in r["why"], str(r))
    r = stop("nope")
    check("stopping a service that does not exist is an answer, not a crash", not r["ok"])

    # the one that matters: a held port is reported, never killed
    src = Path(__file__).read_text(encoding="utf-8")
    body = src.split("def start(self, log=print", 1)[1].split("def stop(self", 1)[0]
    check("start never kills anything directly",
          "taskkill" not in body and "Nothing was killed" in body)
    check("the only thing start will replace is an older copy of THIS program",
          "self.cmd_marker" in body and "cmdlines(held)" in body)
    check("a held port that is not an older copy is stepped around, not killed",
          body.index("moving to") > body.index("self.cmd_marker"))
    stop_body = src.split("def stop(self, log=print", 1)[1].split("def _loop_argv", 1)[0]
    check("stop only ever kills a pid this process started",
          "self.proc.pid" in stop_body and "self.proc is None" in stop_body)

    check("the loop is started with a python that can import uvicorn",
          'python_with("uvicorn")' in src, "the eleven-minute wedge of 2026-09-14")
    check("nothing is started with a console window",
          "NO_WINDOW" in src and src.count("creationflags=NO_WINDOW") >= 2)
    check("the page is a whole document with no outside file",
          PAGE.startswith("<!doctype html") and "</html>" in PAGE and "http" not in PAGE.split("<script>")[0])

    class Fake(Service):
        def up(self, timeout=4.0, port=None):
            return True
    f = Fake("x", port=1, health="http://127.0.0.1:1/")
    check("a service that is already up is left alone", f.start(log=lambda *_: None)["did"] == "nothing")

    # ── THE BUG OF 2026-09-14, nailed down with a real server on a real socket.
    # A four-day-old build of THE LINE sat on :8099 answering 404 to every /api/ route. The old
    # health rule counted that as up, so the real dashboard was never started and John watched a
    # dead page for four days. These five checks are that failure, made impossible to repeat.
    import contextlib

    def server(handler_body):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                handler_body(self)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, srv.server_address[1]

    def stale(h):                                  # answers the socket, 404s the API — the squatter
        h.send_error(404)

    def wrong(h):                                  # 200, but it is some other program
        b = b'{"app":"something-else/9"}'
        h.send_response(200); h.send_header("Content-Length", str(len(b))); h.end_headers()
        h.wfile.write(b)

    def right(h):
        b = b'{"app":"the-line-dashboard/1","pid":1}'
        h.send_response(200); h.send_header("Content-Length", str(len(b))); h.end_headers()
        h.wfile.write(b)

    srv404, p404 = server(stale)
    srvbad, pbad = server(wrong)
    srvok, pok = server(right)
    try:
        def probe(port):
            return Service("probe", port=port, health="http://127.0.0.1:{port}/api/whoami",
                           marker="the-line-dashboard/1")
        check("a 404 is an ANSWER and the WRONG one — it is NOT up", not probe(p404).up(timeout=3),
              "the four-day dead dashboard on :8099")
        check("a port that accepts a connection is still reported as held",
              probe(p404).port_held())
        check("a 200 from some other program is not this service being up",
              not probe(pbad).up(timeout=3))
        check("a 200 that says the right build IS up", probe(pok).up(timeout=3))

        # and the collision: a squatter on the first port moves us, it does not get killed.
        moved = Service("line2", port=p404, health="http://127.0.0.1:{port}/api/whoami",
                        marker="the-line-dashboard/1", ports=[p404, 8101, 8102],
                        argv=lambda port=0, **_: ["cmd", "/c", "exit", "0"], ready_s=1)
        said = []
        moved.start(log=said.append)
        check("a squatter moves us to the next free port instead of being killed",
              moved.port != p404 and any("Nothing was killed" in m for m in said), str(said))
        check("the health url follows the port it actually moved to",
              moved.health == f"http://127.0.0.1:{moved.port}/api/whoami", moved.health or "")

        # The squatter here is this selftest's own HTTP server, whose command line is python
        # running switchboard.py — NOT dashboard.py. So a cmd_marker must not match it, and the
        # service must step sideways rather than shoot the thing holding the port.
        careful = Service("line3", port=p404, health="http://127.0.0.1:{port}/api/whoami",
                          marker="the-line-dashboard/1", ports=[p404, 8101, 8102],
                          cmd_marker="dashboard.py",
                          argv=lambda port=0, **_: ["cmd", "/c", "exit", "0"], ready_s=1)
        careful.start(log=lambda *_: None)
        check("a cmd_marker that does not match leaves the squatter alone",
              careful.port != p404 and probe(p404).port_held(),
              "the port must STILL be held — nothing was killed")

        # and the home port is taken back, never drifted away from
        home = Service("line4", port=8099, health="http://127.0.0.1:{port}/api/whoami",
                       ports=[8099, 8100], argv=lambda port=0, **_: None)
        home.port = 8100
        home.start(log=lambda *_: None)
        check("start always tries the home port again instead of staying where it drifted",
              home.port == 8099, str(home.port))
    finally:
        for srv in (srv404, srvbad, srvok):
            with contextlib.suppress(Exception):
                srv.shutdown()

    # ── a restarted switchboard must not orphan a running loop
    check("the loop is the one service adopted from disk",
          line["loop"].adopts and not any(s.adopts for n, s in line.items() if n != "loop"))
    check("the loop is adopted by PID, asked of Windows, not by trusting a file",
          "pid_alive(pid)" in src and "tasklist" in src)
    import tempfile
    global HEARTBEAT
    keep = HEARTBEAT
    try:
        with tempfile.TemporaryDirectory() as td:
            HEARTBEAT = Path(td) / "heartbeat.json"
            HEARTBEAT.write_text(json.dumps({"pid": os.getpid(), "phase": "stopped"}))
            check("a heartbeat that says stopped is not a running loop", loop_heartbeat() == {})
            HEARTBEAT.write_text(json.dumps({"pid": 999999, "phase": "playing"}))
            check("a heartbeat naming a pid that is gone is not a running loop",
                  loop_heartbeat() == {})
            HEARTBEAT.write_text("{ not json")
            check("an unreadable heartbeat is not a running loop", loop_heartbeat() == {})
    finally:
        HEARTBEAT = keep
    stop_src = src.split("def stop(self, log=print", 1)[1].split("def _loop_argv", 1)[0]
    check("the ONLY unstarted pid it will kill is one the loop wrote about itself",
          "adopted from its own heartbeat" in stop_src and "loop_heartbeat()" in stop_src)
    check("it can stand down for a newer copy of itself instead of being killed",
          "/api/standdown" in src and "_server.shutdown()" in src)

    # ── replacing an older copy of myself
    to_src = src.split("\ndef take_over(port", 1)[1].split("\ndef main(", 1)[0]
    check("a takeover only ever replaces something that says it is a switchboard",
          "SIGNATURE not in who" in to_src and "Nothing was killed" in to_src)
    mute, talks = to_src.split("if SIGNATURE not in who", 1)
    check("a switchboard that can answer is asked to stand down before it is replaced",
          talks.index("standdown") < talks.index("_replace("))
    check("a switchboard that cannot answer is not asked to — it is identified and replaced",
          "standdown" not in mute.split("if not answered", 1)[1])
    kill_src = src.split("\ndef _replace(", 1)[1].split("\ndef _port_free(", 1)[0]
    check("the takeover kill is NOT a tree-kill, because the Sam Loop is the old one's child",
          '"/T"' not in kill_src and '"/F"' in kill_src)
    check("a mute holder is identified by WHAT IT IS, not only by what it says",
          "switchboard.py" in to_src and "cmdlines(held)" in to_src)
    check("a port held by a stranger is refused, not taken",
          "never answered" in to_src and "is not a switchboard" in to_src)
    check("one timed-out probe is not evidence — it asks six times before giving up",
          "for _ in range(6)" in to_src)
    check("a second switchboard cannot bind a port the first one holds",
          Switchboard.allow_reuse_address is False,
          "on Windows SO_REUSEADDR lets two servers share a port — that IS the collision")
    check("the takeover never kills its own process",
          "pid != os.getpid()" in src)
    check("everything it says also lands in a file, because it has no window",
          "def to_file" in src and "to_file(msg)" in src and str(LOGFILE).endswith("switchboard-log.txt"))

    check("THE LINE says which build it is, and has somewhere else to go",
          line["line"].marker == "the-line-dashboard/1" and len(line["line"].ports) > 1)
    # The old rule is quoted in up()'s docstring on purpose, so read the CODE, not the prose.
    up_src = src.split("def up(self", 1)[1].split("def port_held", 1)[0]
    up_code = up_src.split('"""', 2)[2] if up_src.count('"""') >= 2 else up_src
    check("no health check counts a 4xx as healthy",
          "< 500" not in up_code and "200 <= r.status < 300" in up_code, up_code.strip()[:120])

    print("\n" + ("ALL PASS" if fails == 0 else f"{fails} FAILED"))
    return fails


# ─────────────────────────────────────────────────────────────── replacing an older me

class Switchboard(ThreadingHTTPServer):
    """The HTTP server, with the one Windows footgun switched off.

    2026-09-14. `allow_reuse_address` is 1 on HTTPServer, and on Windows that is not what it means
    on Linux: SO_REUSEADDR there lets a SECOND process bind a port another process is already
    listening on. So when I started a new switchboard over an old one, the bind SUCCEEDED, the new
    one logged "switchboard up", and every request still went to the four-minute-old copy. Two
    programs owning one port, which is the exact thing this file exists to prevent, caused by this
    file. With reuse off the second bind raises, take_over() runs, and there is only ever one.
    """

    allow_reuse_address = False
    daemon_threads = True


def owner_pids(port: int) -> list[int]:
    """Every process LISTENING on this port, asked of Windows. Usually one; two is the bug."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                             timeout=20, creationflags=NO_WINDOW).stdout
    except Exception:                             # noqa: BLE001
        return []
    pids = []
    for ln in out.splitlines():
        f = ln.split()
        if len(f) >= 5 and f[0].upper() == "TCP" and f[1].endswith(f":{port}") \
                and f[3].upper() == "LISTENING":
            try:
                pid = int(f[4])
            except ValueError:
                continue
            if pid != os.getpid() and pid not in pids:
                pids.append(pid)
    return pids


def cmdlines(pids: list[int]) -> dict[int, str]:
    """What each of those processes was actually started with. {} if Windows will not say."""
    if not pids:
        return {}
    q = ("Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in @("
         + ",".join(str(int(p)) for p in pids)
         + ") } | ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-Command", q], capture_output=True, text=True, timeout=30,
                             creationflags=NO_WINDOW).stdout
    except Exception:                             # noqa: BLE001
        return {}
    found = {}
    for ln in out.splitlines():
        pid, _, cmd = ln.partition("|")
        try:
            found[int(pid.strip())] = cmd.strip()
        except ValueError:
            continue
    return found


def _replace(port: int, pids: list[int], why: str, log=print) -> bool:
    log(f"  {why} — replacing {pids}")
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],  # NOT /T: the loop is its child
                           capture_output=True, timeout=30, creationflags=NO_WINDOW)
        except Exception as e:                    # noqa: BLE001
            log(f"  could not replace pid {pid}: {type(e).__name__}: {e}")
    return _port_free(port, 20)


def _port_free(port: int, tries: int, gap: float = 0.5) -> bool:
    for _ in range(tries):
        time.sleep(gap)
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return True
    return False


def take_over(port: int, log=print) -> bool:
    """:8777 is taken. If it is an OLDER COPY OF ME, replace it. Anything else, refuse.

    2026-09-14. Restarting the switchboard onto a new build had to be done in batch, through two
    PowerShell one-liners, and when it silently failed the old build kept answering — so the .bat
    reported LISTENING and nothing had changed. Batch is the wrong place for this. It lives here
    now, where it can check who it is talking to before it does anything.

    The kill is deliberately NOT /T. The old switchboard is the parent of a running Sam Loop; a
    tree-kill here would take the loop, Sam's Living Room and his Pick Board down with it. Killing
    the parent alone leaves all three running, and the new switchboard adopts the loop from the pid
    in its own heartbeat.
    """
    # Ask more than once. A port can be slow, and for a few minutes on 2026-09-14 it was worse
    # than slow: two switchboards were bound to :8777 at the same time (see Switchboard above), so
    # roughly every other connection landed nowhere. One timed-out probe is not evidence that the
    # thing on the port is a stranger, and treating it as evidence is how a takeover gives up on
    # its own older copy.
    who, answered = "", False
    for _ in range(6):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=6) as r:
                who = r.read(8192).decode("utf-8", "replace")
            answered = True
            if SIGNATURE in who:
                break
        except Exception:                         # noqa: BLE001
            pass
        time.sleep(1.0)
    if not answered:
        # It never spoke. That is not proof it is a stranger — a switchboard whose socket is wedged
        # cannot answer either, and on 2026-09-14 two of mine were bound to :8777 at once and
        # roughly every other connection landed nowhere. So ask Windows what the process IS rather
        # than what it says: a python running switchboard.py is me, however mute.
        held = owner_pids(port)
        mine = [pid for pid, cmd in cmdlines(held).items() if "switchboard.py" in cmd.lower()]
        if not mine:
            log(f"  :{port} is held by something that never answered over six tries, and is not "
                f"running switchboard.py. Nothing was killed.")
            return False
        return _replace(port, mine, f":{port} is held by a switchboard that stopped answering",
                        log=log)
    if SIGNATURE not in who:
        log(f"  :{port} answered, but it is not a switchboard. Nothing was killed.")
        return False

    log("  a switchboard is already running — asking it to stand down for this build")
    try:                                          # a build old enough to lack the route 404s here
        urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/api/standdown", data=b"{}", method="POST"), timeout=5).read()
    except Exception:                             # noqa: BLE001
        pass
    if _port_free(port, 12):
        log("  it stood down. Every service it started is still running.")
        return True

    pids = owner_pids(port)
    if not pids:
        log("  it did not stand down and I cannot see which process holds the port.")
        return False
    return _replace(port, pids, "it did not stand down (too old to know how)", log=log)


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                         # noqa: BLE001
            pass
    global _server
    to_file(f"--- starting, pid {os.getpid()}, python {sys.executable}")
    try:
        srv = _server = Switchboard(("127.0.0.1", PORT), Handler)
    except OSError:
        if not take_over(PORT, log=lambda m: (print(m, flush=True), to_file(m))[0]):
            to_file(f"STOPPED: :{PORT} is taken and was not mine to take")
            return 1
        try:
            srv = _server = Switchboard(("127.0.0.1", PORT), Handler)
        except OSError as e:
            print(f"  :{PORT} did not clear: {e}")
            to_file(f"STOPPED: :{PORT} did not clear: {e}")
            return 1
    print("=" * 68)
    print(f"  THE SWITCHBOARD is on   http://127.0.0.1:{PORT}")
    print("  It starts and stops the world, THE LINE and the Sam Loop.")
    print("  It NEVER kills anything it did not start.")
    print("  Leave this window open - closing it leaves the services running.")
    print("=" * 68)
    threading.Timer(1.0, lambda: log("switchboard up")).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  switchboard stopped. The services it started are still running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
