"""Send exact additional-03 preview bytes to local Ollama qwen2.5vl with strict JSON."""
from __future__ import annotations
import base64, hashlib, json, urllib.request
from datetime import datetime, timezone
from pathlib import Path

BUNDLE=Path(__file__).resolve().parent
PREVIEW=BUNDLE/'recliner-raw-crop_additional-03-edge-preserving-denoise-eight-panel.png'
OUTPUT=BUNDLE/'local-vision-gate.json'
PROMPT='''Judge the attached eight-panel standalone recliner evidence preview. Top row is neutral topology; bottom row is embedded durable material. Canon checklist: recognizable recliner geometry/silhouette and footrest; exactly one isolated asset with no fused room or ground sheet; visible truthful front/right/rear/left labels; continuous filled surfaces with no point splats/stipple or catastrophic artifacts; broad topology visibility; material continuity and source-like warm upholstered finish; adequate neutral contrast. Pass only if every check passes. Return observations grounded only in visible pixels. Confidence must be from 0.0 to 1.0.'''
SCHEMA={"type":"object","properties":{"pass":{"type":"boolean"},"failed_checks":{"type":"array","items":{"type":"string"}},"confidence":{"type":"number","minimum":0,"maximum":1},"observations":{"type":"array","items":{"type":"string"}},"next_renderer_change":{"type":"string"}},"required":["pass","failed_checks","confidence","observations","next_renderer_change"]}

def sha256(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 payload={"model":"qwen2.5vl:7b","stream":False,"format":SCHEMA,"options":{"temperature":0},"messages":[{"role":"user","content":PROMPT,"images":[base64.b64encode(PREVIEW.read_bytes()).decode('ascii')]}]}
 request=urllib.request.Request('http://127.0.0.1:11434/api/chat',data=json.dumps(payload).encode('utf-8'),headers={'Content-Type':'application/json'},method='POST')
 with urllib.request.urlopen(request,timeout=600) as response: raw=json.loads(response.read().decode('utf-8'))
 verdict=json.loads(raw['message']['content'])
 record={"schema":"unified-world-pipeline.task-11.8.4a.local-vision-gate.v1","recorded_at_utc":datetime.now(timezone.utc).isoformat(),"task":"11.8.4a","attempt":"additional-03","model":"qwen2.5vl:7b","endpoint":"localhost only","preview":{"path":str(PREVIEW),"sha256":sha256(PREVIEW),"bytes_sent_directly":True},"prompt":PROMPT,"verdict":verdict,"transport":{"stream":False,"strict_json_schema":True,"cloud":False},"raw_model_metadata":{"done_reason":raw.get('done_reason'),"total_duration":raw.get('total_duration'),"eval_count":raw.get('eval_count')}}
 OUTPUT.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8'); print(json.dumps(verdict,indent=2))
if __name__=='__main__':main()
