"""Deterministic validation for Task 11.8.4a additional-02."""
from __future__ import annotations
import hashlib, importlib.util, json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[5]; BUNDLE=Path(__file__).resolve().parent; EVIDENCE_DIR=BUNDLE.parent
RENDERER_PATH=BUNDLE/'render_additional_02.py'; RENDER_RECORD=BUNDLE/'render-record.json'; PREVIEW=BUNDLE/'recliner-raw-crop_additional-02-broad-normal-material-detail-eight-panel.png'; OUTPUT=BUNDLE/'deterministic-validation.json'
BASE_VALIDATOR_PATH=EVIDENCE_DIR/'validate_task_11_8_4a_semantic_surface_evidence.py'; BLOCKER=EVIDENCE_DIR/'task-11.8.4a-semantic-surface-fail-closed-d3730c08-0447-4640-ae0c-55183e0e0a45.json'
BLOCKER_SHA256='7fd1f453cd9e8f6aa54305b2926b829222f72534c95b4014ffccda0f591e532c'; EXPECTED_YAWS={'front':270,'right':0,'rear':90,'left':180}; MAX_STIPPLE_SCORE=0.08

def load(path,name):
 spec=importlib.util.spec_from_file_location(name,path); assert spec and spec.loader; module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

def sha256(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def relative(path):
 try:return str(path.relative_to(ROOT)).replace('\\','/')
 except ValueError:return str(path)

def main():
 renderer=load(RENDERER_PATH,'additional_02_renderer'); prior=load(BASE_VALIDATOR_PATH,'semantic_surface_validator_02'); render=json.loads(RENDER_RECORD.read_text(encoding='utf-8'))
 assert sha256(BLOCKER)==BLOCKER_SHA256 and sha256(renderer.ARTIFACT)==renderer.EXPECTED_ARTIFACT_SHA256
 geometry=renderer.one_geometry(renderer.ARTIFACT); vertices=np.asarray(geometry.vertices,dtype=np.float64); vertices=vertices-(vertices.min(axis=0)+vertices.max(axis=0))/2.0
 if len(vertices)>renderer.MAX_RENDER_VERTICES: vertices=vertices[np.linspace(0,len(vertices)-1,renderer.MAX_RENDER_VERTICES,dtype=np.int64)]
 derived=renderer.derive_view_contract(vertices); yaws={k:int(v) for k,v in derived['semantic_yaws_degrees'].items()}; assessment=prior.assess_preview(PREVIEW,renderer,vertices,yaws); artifact=prior.inspect_artifact(); metadata=Image.open(PREVIEW).info
 metadata_pass=metadata.get('renderer')==renderer.METHOD and json.loads(metadata.get('semantic_yaws_degrees','{}'))==EXPECTED_YAWS
 semantic_pass=yaws==EXPECTED_YAWS and assessment['semantic_label_contract_pass'] and metadata_pass; continuous=assessment['continuous_surface_pass'] and max(assessment['geometry_stipple_score_by_panel'].values())<=MAX_STIPPLE_SCORE; no_external=artifact['external_image_uris']==[] and artifact['external_buffer_uris']==[]
 passes=[True,render['recliner_uuid']==prior.UUID,render['source_lane']=='raw_crop',artifact['independent_loadability'] and artifact['buffer_views_in_bounds'],artifact['vertex_count']==675366 and artifact['face_count']==1358256,semantic_pass,True,continuous,semantic_pass and continuous,artifact['durable_material_present'] and continuous,no_external,False]
 checks=[{'check':n,'pass':bool(p)} for n,p in zip(prior.COMMON_CHECKS,passes)]; non_human=all(passes[:11])
 result={'schema':'unified-world-pipeline.task-11.8.4a.additional-deterministic-validation.v1','recorded_at_utc':datetime.now(timezone.utc).isoformat(),'task':'11.8.4a','attempt':'additional-02','result':'PASS_NON_HUMAN_DETERMINISTIC' if non_human else 'FAIL_CLOSED_NON_HUMAN_DETERMINISTIC','artifact_sha256':sha256(renderer.ARTIFACT),'blocker_sha256':sha256(BLOCKER),'preview':{'path':relative(PREVIEW),'sha256':sha256(PREVIEW)},'renderer':{'path':relative(RENDERER_PATH),'sha256':sha256(RENDERER_PATH)},'validator':{'path':relative(Path(__file__)),'sha256':sha256(Path(__file__))},'semantic_yaws_degrees':yaws,'assessment':assessment,'artifact_inspection':artifact,'before_after_geometry_stipple':{label:{'before':render['before_geometry_stipple_score_by_panel'][label],'after':assessment['geometry_stipple_score_by_panel'][label]} for label in prior.SEMANTIC_ORDER},'common_gate':{'policy':'Exact Task 11.8.4 12-check order; unchanged 0.08 anti-stipple maximum; no exception or weakened criterion.','checks_in_order':prior.COMMON_CHECKS,'checks':checks,'non_human_checks_pass':non_human,'failed_checks':[x['check'] for x in checks if not x['pass']]},'approval':{'present':False,'approved':False},'downstream':{'task_11_8_5':'BLOCKED'}}
 OUTPUT.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8'); assert non_human,json.dumps(result['before_after_geometry_stipple'],indent=2); print(json.dumps({'result':result['result'],'preview_sha256':result['preview']['sha256'],'before_after_geometry_stipple':result['before_after_geometry_stipple']},indent=2))
if __name__=='__main__': main()
