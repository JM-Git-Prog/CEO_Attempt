"""Live QA grading app — shows test session artifacts as they're generated."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
QA_LOG = OUTPUT_DIR / "human_qa_log.jsonl"

app = FastAPI(title="QA Validator")


@app.get("/api/qa/sessions")
async def list_sessions():
    sessions = []
    candidates = []
    for d in OUTPUT_DIR.iterdir():
        if not d.is_dir() or not (d / "session.json").exists():
            continue
        candidates.append((d.stat().st_mtime, d))
    candidates.sort(reverse=True)
    for _, d in candidates[:40]:
        try:
            data = json.loads((d / "session.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        has_blockout = bool(list(d.glob("blockout_v*.png")))
        has_canon = bool(list(d.glob("canon_v*.png")))
        has_svg = bool(list(d.glob("floor_plan_v*.svg")))
        if not (has_blockout or has_canon or has_svg):
            continue
        desc = (data.get("user_description") or "").replace("\n", " ").replace("\r", "")[:100]
        sessions.append({
            "id": d.name,
            "state": data.get("state", "?"),
            "desc": desc,
            "v": data.get("interface_version") or "?",
            "blockout": has_blockout,
            "canon": has_canon,
            "svg": has_svg,
        })
    return sessions


@app.get("/api/qa/session/{sid}")
async def get_session(sid: str):
    d = OUTPUT_DIR / sid
    if not (d / "session.json").exists():
        return JSONResponse({"error": "not found"}, 404)
    data = json.loads((d / "session.json").read_text(encoding="utf-8"))
    blockouts = sorted(d.glob("blockout_v*.png"))
    canons = sorted(d.glob("canon_v*.png"))
    svgs = sorted(d.glob("floor_plan_v*.svg"))
    return {
        "id": sid,
        "desc": (data.get("user_description") or "").replace("\r", ""),
        "state": data.get("state"),
        "v": data.get("interface_version"),
        "plan": data.get("floor_plan"),
        "blockouts": [f"/api/qa/file/{sid}/{p.name}" for p in blockouts],
        "canons": [f"/api/qa/file/{sid}/{p.name}" for p in canons],
        "svgs": [f"/api/qa/file/{sid}/{p.name}" for p in svgs],
    }


@app.get("/api/qa/file/{sid}/{filename}")
async def get_file(sid: str, filename: str):
    path = OUTPUT_DIR / sid / filename
    if not path.exists() or ".." in filename:
        return JSONResponse({"error": "not found"}, 404)
    mt = "image/png" if filename.endswith(".png") else "image/svg+xml"
    return FileResponse(path, media_type=mt)


@app.post("/api/qa/grade")
async def grade(request: Request):
    body = await request.json()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": body.get("session_id"),
        "verdict": body.get("verdict"),
        "notes": body.get("notes", ""),
        "marks": body.get("marks", []),
    }
    with open(QA_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return {"ok": True}


@app.get("/api/qa/grades")
async def grades():
    if not QA_LOG.exists():
        return []
    return [json.loads(l) for l in QA_LOG.read_text("utf-8").strip().split("\n") if l.strip()]


@app.get("/", response_class=HTMLResponse)
async def index():
    return PAGE


PAGE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>QA</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui;background:#111;color:#eee;display:flex;height:100vh}
#side{width:240px;overflow-y:auto;background:#1a1a1a;border-right:1px solid #333;padding:8px}
#side h2{font-size:12px;color:#888;padding:4px 0;text-transform:uppercase}
.card{padding:8px;margin:4px 0;border:1px solid #333;border-radius:4px;cursor:pointer;font-size:11px}
.card:hover{background:#222}.card.sel{background:#1a3a5a;border-color:#4a9eff}
.card b{color:#6af;font-family:monospace}
#main{flex:1;overflow-y:auto;padding:16px}
.prompt{background:#1a1a1a;border:1px solid #333;border-radius:6px;padding:12px;font-size:12px;white-space:pre-wrap;max-height:150px;overflow-y:auto;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:12px;margin-bottom:16px}
.art{border:1px solid #333;border-radius:6px;overflow:hidden;position:relative}
.art h4{background:#0a0a0a;padding:6px 10px;font-size:11px;color:#888}
.art img{width:100%;display:block;cursor:crosshair}
.art canvas{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none}
.bar{display:flex;gap:8px;align-items:center;margin-bottom:12px}
.bar button{padding:6px 16px;border-radius:4px;border:none;cursor:pointer;font-size:13px;font-weight:600}
.bar .p{background:#238636;color:#fff}.bar .f{background:#da3633;color:#fff}.bar .m{background:#d29922;color:#000}
textarea{width:100%;background:#1a1a1a;border:1px solid #333;color:#eee;padding:8px;border-radius:4px;font-size:12px;resize:vertical;min-height:50px}
.status{font-size:11px;color:#888;margin-top:8px}
</style></head><body>
<div id="side"><h2>Sessions (auto-refresh)</h2><div id="list">Loading...</div></div>
<div id="main"><p style="color:#888;padding:40px;text-align:center">Select a session or wait for new ones to appear.</p></div>
<script>
let cur=null,marks=[];
async function load(){
 try{
  const r=await fetch('/api/qa/sessions');const d=await r.json();
  document.getElementById('list').innerHTML=d.map(s=>'<div class="card'+(cur&&cur.id===s.id?' sel':'')+'" onclick="pick(\''+s.id+'\')"><b>'+s.id+'</b> v'+s.v+'<br>'+esc(s.desc.slice(0,60))+'</div>').join('');
 }catch(e){document.getElementById('list').innerHTML='<p style="color:red">'+e+'</p>';}
}
async function pick(id){
 const r=await fetch('/api/qa/session/'+id);cur=await r.json();marks=[];render();load();
}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function render(){
 if(!cur){document.getElementById('main').innerHTML='';return;}
 let h='<div class="prompt">'+esc(cur.desc)+'</div>';
 h+='<div class="grid">';
 (cur.svgs||[]).forEach((u,i)=>{h+='<div class="art" data-u="'+u+'"><h4>Floor Plan</h4><img src="'+u+'" onload="sizeC(this)"><canvas></canvas></div>';});
 (cur.blockouts||[]).forEach((u,i)=>{h+='<div class="art" data-u="'+u+'"><h4>Blockout</h4><img src="'+u+'" onload="sizeC(this)"><canvas></canvas></div>';});
 (cur.canons||[]).forEach((u,i)=>{h+='<div class="art" data-u="'+u+'"><h4>Canon</h4><img src="'+u+'" onload="sizeC(this)"><canvas></canvas></div>';});
 h+='</div>';
 h+='<div class="bar"><button class="p" onclick="grade(\'pass\')">PASS</button><button class="m" onclick="grade(\'partial\')">PARTIAL</button><button class="f" onclick="grade(\'fail\')">FAIL</button></div>';
 h+='<textarea id="notes" placeholder="Notes / concerns..."></textarea>';
 h+='<div class="status" id="st"></div>';
 document.getElementById('main').innerHTML=h;
 document.querySelectorAll('.art img').forEach(img=>{img.onclick=function(e){markImg(e,this);}});
}
function sizeC(img){const c=img.parentElement.querySelector('canvas');if(c){c.width=img.naturalWidth;c.height=img.naturalHeight;}}
function markImg(e,img){
 const r=img.getBoundingClientRect();
 const x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;
 const note=prompt('Concern at this point?')||'';
 const u=img.parentElement.dataset.u;
 marks.push({u,x,y,note});
 drawMarks(img.parentElement);
}
function drawMarks(art){
 const c=art.querySelector('canvas');if(!c)return;
 const ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);
 const u=art.dataset.u;
 marks.filter(m=>m.u===u).forEach(m=>{
  const px=m.x*c.width,py=m.y*c.height;
  ctx.beginPath();ctx.arc(px,py,12,0,Math.PI*2);ctx.strokeStyle='#f55';ctx.lineWidth=3;ctx.stroke();
  if(m.note){ctx.font='12px system-ui';ctx.fillStyle='#f55';ctx.fillText(m.note.slice(0,25),px+14,py+4);}
 });
}
async function grade(v){
 if(!cur)return;
 const notes=document.getElementById('notes')?.value||'';
 await fetch('/api/qa/grade',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:cur.id,verdict:v,notes,marks})});
 document.getElementById('st').textContent='Recorded: '+v+' ('+marks.length+' marks) at '+new Date().toLocaleTimeString();
}
load();setInterval(load,5000);
</script></body></html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8501)
