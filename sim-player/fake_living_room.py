"""sim-player/fake_living_room.py — a stand-in for V17 + the Pick Board + the builder, for tests.

Speaks exactly the slice of the contract sam.py speaks (see sam.py's docstring), with the timing
collapsed: a wall goes up after two polls, a pick builds after two more and bumps the sim world's
version file on disk. No model, no UPBGE, no network beyond 127.0.0.1. stdlib only.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOUSE_WORDS = re.compile(r"\b(house|home|porch|roof|garage|cottage|mansion)\b", re.I)
COMPLAINT = re.compile(r"nothing happened|where is it|still just|not there", re.I)


class FakeLivingRoom:
    def __init__(self, worlds: Path, slug: str = "sim-neighborhood", host: str = "127.0.0.1"):
        self.worlds, self.slug, self.host = worlds, slug, host
        self.visions: dict[str, list[str]] = {}
        self.cards: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.stations: dict[str, dict] = {}
        self.confirms: list[str] = []
        self.says: list[dict] = []
        self._n = 0
        self._server = None
        self._thread = None
        self.url = ""
        self.seed_world(0)

    # ── world files, like the builder writes them ──
    def seed_world(self, version: int, houses: int = 4) -> None:
        wd = self.worlds / self.slug / "output" / "world"
        wd.mkdir(parents=True, exist_ok=True)
        man = {"slug": self.slug, "brief": {"houses": [{"style": "colonial"}] * houses},
               "lots": {"empty": [f"L{i}" for i in range(5, 17 - (houses - 4))], "next": [-22, 0, 58]}}
        (wd / f"{version}-world.json").write_text(json.dumps(man), encoding="utf-8")

    def version(self) -> int:
        wd = self.worlds / self.slug / "output" / "world"
        return max(int(f.name.split("-")[0]) for f in wd.iterdir() if re.match(r"^\d+-world\.json$", f.name))

    # ── the app ──
    def say(self, body: dict) -> tuple[int, dict]:
        session, message = str(body.get("session") or ""), str(body.get("message") or "")
        self.says.append(body)
        if not session or not message:
            return 400, {"error": "session and message are required"}
        dec = body.get("card_decision")
        if isinstance(dec, dict) and dec.get("chose") == "build":
            card = self.cards.get(str(dec.get("id")))
            if not card:
                return 404, {"error": "that plan is gone (V17 restarted?) — say it again"}
            self.confirms.append(session)
            return 200, {"kind": "house", "confidence": 1.0, "reason": "plan confirmed", "card": None,
                         "card_clause": card["summary"], "card_id": card["id"], "receipt": {"got": card["summary"]}}
        lines = self.visions.get(session)
        if lines is not None:
            if re.fullmatch(r"\s*(start over|forget that)\s*", message, re.I):
                del self.visions[session]
                return 200, {"kind": "vision", "reply": "Okay, fresh start — tell me about the place you want.", "summary": None, "question": None, "vision": None}
            if re.fullmatch(r"\s*(build it|ok build it|yes build it)\s*[.!]?\s*", message, re.I):
                text = " · ".join(lines)
                del self.visions[session]
                self._n += 1
                card = {"id": f"card{self._n}", "name": "Porch House", "summary": f"A house with a big porch ({text}).",
                        "plan": ["Survey.", "Foundation.", "Frame.", "Roof.", "Porch.", "Finish."], "parts": ["slab", "porch ×1"],
                        "part_count": 2, "assumptions": ["two floors"], "questions": ["Which way should the porch face?"],
                        "options": [{"kind": "build", "label": "Build it as planned"}, {"kind": "revise", "label": "Change something first"}],
                        "brief": text, "model": "fake", "seconds": 1}
                self.cards[card["id"]] = card
                return 200, {"kind": "house", "confidence": 0.9, "reason": "a house", "card": card, "vision_built": text, "receipt": {"got": text}}
            lines.append(message)
            q = "What kind of roof — shingles, metal, or flat?" if len(lines) == 2 else None
            return 200, {"kind": "vision", "reply": f"Got it — {message}." + (f" {q}" if q else ""), "summary": "So far: " + " · ".join(lines),
                         "question": q, "vision": {"lines": list(lines)}}
        if HOUSE_WORDS.search(message):
            self.visions[session] = [message]
            q = "How many floors — one or two?"
            return 200, {"kind": "vision", "reply": f"Got it — {message}. {q}", "summary": "So far: " + message, "question": q, "vision": {"lines": [message]}}
        if COMPLAINT.search(message):
            return 200, {"kind": "problem", "confidence": 0.9, "reason": "Noted: nothing looks changed from here.", "receipt": {}}
        return 200, {"kind": "gap", "confidence": 0.8, "reason": "not something the workshop can make yet",
                     "receipt": {"got": None, "making": None, "needs": message}, "gaps_filed": [message]}

    def order(self, body: dict) -> tuple[int, dict]:
        text, base = str(body.get("text") or ""), str(body.get("base") or "")
        if not text:
            return 400, {"error": "empty sentence"}
        if base != self.slug:
            return 400, {"error": f"the fake only builds {self.slug}, not {base!r}"}
        self._n += 1
        oid = f"o{self._n}"
        self.orders[oid] = {"text": text, "polls": 0, "stage": "rendering", "station": None, "build_job": None, "built": False}
        return 200, {"order": oid, "brief": {"houses": [{"style": "colonial", "porch": True}], "gaps": []}, "stage": "rendering"}

    def order_status(self, oid: str) -> tuple[int, dict]:
        o = self.orders.get(oid)
        if not o:
            return 404, {"error": "unknown order (V17 restarted?) — say it again"}
        o["polls"] += 1
        if o["stage"] == "rendering" and o["polls"] >= 2:
            sid = f"house-{oid}"
            self.stations[sid] = {"id": sid, "kind": "wall", "question": "Which house?", "answer": None,
                                  "items": [{"tag": f"c{i}", "label": f"take {i}", "image": f"/img/{i}.png"} for i in (1, 2, 3)], "actions": {"right": "more"}}
            o["stage"], o["station"] = "on the wall", sid
        if o["stage"] == "on the wall":
            ans = self.stations[o["station"]].get("answer")
            if ans and ans.get("action") == "choose":
                o["stage"], o["build_job"], o["build_polls"] = "building", f"b{oid}", 0
            elif ans and ans.get("action") == "more":
                self._n += 1
                nid = f"o{self._n}"
                self.orders[nid] = {"text": o["text"], "polls": 0, "stage": "rendering", "station": None, "build_job": None, "built": False}
                o["stage"], o["next_order"] = "more", nid
                return 200, {"order": oid, "stage": "more", "next_order": nid, "station": o["station"]}
            else:
                return 200, {"order": oid, "stage": "on the wall", "station": o["station"], "count": 3}
        if o["stage"] == "building":
            o["build_polls"] = o.get("build_polls", 0) + 1
            if o["build_polls"] >= 2 and not o["built"]:
                self.seed_world(self.version() + 1, houses=5)
                o["built"] = True
            return 200, {"order": oid, "stage": "building", "build_job": o["build_job"], "station": o["station"],
                         "jobsite": {"stage": "building", "progress": {"note": "walls going up", "step": 3, "steps": 7}}}
        return 200, {"order": oid, "stage": o["stage"]}

    def job(self, oid: str) -> tuple[int, dict]:
        if oid not in self.orders:
            return 404, {"error": "no job"}
        return 200, {"candidates": [{"tag": f"c{i}"} for i in (1, 2, 3)], "houses": [{"features_built": ["porch"]}], "unbuilt_features": []}

    def station_answer(self, sid: str, body: dict) -> tuple[int, dict]:
        s = self.stations.get(sid)
        if not s:
            return 404, {"error": f"no station {sid}"}
        if s.get("answer"):
            return 409, {"error": "already answered", "answer": s["answer"]}
        action = str(body.get("action") or "")
        if action == "choose":
            tag = str(body.get("tag") or "")
            if not any(it["tag"] == tag for it in s["items"]):
                return 400, {"error": f"no picture {tag} on this wall"}
            s["answer"] = {"action": "choose", "tag": tag}
        elif action == "more":
            s["answer"] = {"action": "more", "tag": None}
        else:
            return 400, {"error": "action must be choose, more or withdraw"}
        return 200, {"ok": True, "answer": s["answer"]}

    # ── the server ──
    def start(self) -> str:
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                raw = json.dumps(obj).encode("utf-8")
                self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw)))
                self.end_headers(); self.wfile.write(raw)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    return json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return {}

            def do_GET(self):
                p = self.path.split("?")[0]
                if p == "/api/v17/pipeline":
                    return self._send(200, {"ok": True})
                if p == "/api/stations":
                    return self._send(200, {"stations": list(fake.stations.values())})
                m = re.match(r"^/api/v17/neighbourhood/order/([^/]+)$", p)
                if m:
                    return self._send(*fake.order_status(m.group(1)))
                m = re.match(r"^/api/v17/neighbourhood/job/([^/]+)$", p)
                if m:
                    return self._send(*fake.job(m.group(1)))
                self._send(404, {"error": "no route " + p})

            def do_POST(self):
                p = self.path.split("?")[0]
                body = self._body()
                if p == "/api/v17/say":
                    return self._send(*fake.say(body))
                if p == "/api/v17/neighbourhood/order":
                    return self._send(*fake.order(body))
                m = re.match(r"^/api/stations/([^/]+)/answer$", p)
                if m:
                    return self._send(*fake.station_answer(m.group(1), body))
                self._send(404, {"error": "no route " + p})

        self._server = ThreadingHTTPServer((self.host, 0), H)
        self.url = f"http://{self.host}:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._server:
            self._server.shutdown(); self._server.server_close()
