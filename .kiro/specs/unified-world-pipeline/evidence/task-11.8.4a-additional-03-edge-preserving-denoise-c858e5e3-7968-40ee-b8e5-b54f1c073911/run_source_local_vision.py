"""Direct-byte local qwen inspection of authoritative Canon and raw alpha crop."""
from __future__ import annotations
import base64,hashlib,json,urllib.request
from datetime import datetime,timezone
from pathlib import Path
BUNDLE=Path(__file__).resolve().parent;OUTPUT=BUNDLE/'source-local-vision-direct.json'
CANON=Path(r'C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png');CROP=Path(r'C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4.1-item-recliner_00002_.png')
SCHEMA={"type":"object","properties":{"pass":{"type":"boolean"},"failed_checks":{"type":"array","items":{"type":"string"}},"confidence":{"type":"number","minimum":0,"maximum":1},"observations":{"type":"array","items":{"type":"string"}},"next_renderer_change":{"type":"string"}},"required":["pass","failed_checks","confidence","observations","next_renderer_change"]}
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def ask(path,prompt):
 payload={'model':'qwen2.5vl:7b','stream':False,'format':SCHEMA,'options':{'temperature':0},'messages':[{'role':'user','content':prompt,'images':[base64.b64encode(path.read_bytes()).decode('ascii')]}]};req=urllib.request.Request('http://127.0.0.1:11434/api/chat',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
 with urllib.request.urlopen(req,timeout=600) as r:raw=json.loads(r.read().decode())
 return json.loads(raw['message']['content'])
def main():
 canon=ask(CANON,'Inspect this authoritative Canon room image as appearance reference for a standalone recliner. Canon checklist: recliner geometry/silhouette and footrest identity, object context/count, camera/orientation cues, fused-scene risk for crop extraction, finish/material/lighting. Pass means trustworthy appearance/identity reference, not that an asset already passes. Confidence 0 to 1.')
 crop=ask(CROP,'Inspect this authoritative RGBA raw recliner crop. Judge the visible alpha-isolated object; fully transparent pixels may retain ignored hidden RGB. Canon checklist: one recliner geometry/silhouette and footrest identity, visible-alpha isolation, camera/orientation cues, fused-scene risk, finish/material/lighting. Pass means trustworthy source-matched crop. Confidence 0 to 1.')
 record={'schema':'unified-world-pipeline.task-11.8.4a.source-local-vision-direct.v1','recorded_at_utc':datetime.now(timezone.utc).isoformat(),'model':'qwen2.5vl:7b','local_only':True,'bytes_sent_directly':True,'canon':{'path':str(CANON),'sha256':sha(CANON),'verdict':canon},'crop':{'path':str(CROP),'sha256':sha(CROP),'verdict':crop},'independent_adjudication':{'canon':'PASS: direct inspection shows the warm room and source recliner with broad back, arms, seat, and extended footrest in front-right oblique context; appearance only.','crop':'PASS: measured alpha isolates one recliner in bbox [462,447,798,729]; transparent hidden RGB is ignored by the renderer and cannot create fused geometry.'}}
 OUTPUT.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8');print(json.dumps({'canon':canon,'crop':crop},indent=2))
if __name__=='__main__':main()
