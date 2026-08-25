"""Validate the immutable Task 11.8.4a additional-attempt approval candidate."""
from __future__ import annotations
import hashlib,importlib.util,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];EVIDENCE_DIR=Path(__file__).resolve().parent
EVIDENCE=EVIDENCE_DIR/'task-11.8.4a-approval-candidate-additional-03-7c9f6b25-130e-4f47-838c-4cecd86f6d34.json'
BASE_VALIDATOR=EVIDENCE_DIR/'validate_task_11_8_4a_semantic_surface_evidence.py'
ARTIFACT=EVIDENCE_DIR/'task-11.8.4a-continuity-corrected-raw-crop-recliner-3876cc8a-81a2-4bba-9da0-185ba59db002'/'recliner-raw-crop_continuity-corrected-fabric-pbr.glb'
BLOCKER=EVIDENCE_DIR/'task-11.8.4a-semantic-surface-fail-closed-d3730c08-0447-4640-ae0c-55183e0e0a45.json'
EXPECTED_ARTIFACT='4ca7009199ddcacf1eee2234423d8fcee2086e1b3b3ed7ecc78ca69916cedeaf';EXPECTED_BLOCKER='7fd1f453cd9e8f6aa54305b2926b829222f72534c95b4014ffccda0f591e532c'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path,name):
 s=importlib.util.spec_from_file_location(name,path);assert s and s.loader;m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def fingerprint_excluding(excluded):
 head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();listed=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=ROOT).split(b'\0');paths=sorted(x.decode('utf-8') for x in listed if x and x.decode('utf-8')!=excluded);d=hashlib.sha256();d.update(head.encode('ascii')+b'\n')
 for path in paths:d.update(path.encode('utf-8'));d.update(b'\0');d.update((ROOT/path).read_bytes())
 return head,d.hexdigest(),len(paths)
def main():
 r=json.loads(EVIDENCE.read_text(encoding='utf-8'));base=load(BASE_VALIDATOR,'approval_candidate_base');assert r['schema']=='unified-world-pipeline.task-11.8.4a.approval-candidate.v1';assert sha(ARTIFACT)==EXPECTED_ARTIFACT==r['artifact']['sha256'];assert sha(BLOCKER)==EXPECTED_BLOCKER==r['prior_blocker']['sha256']
 for item in r['hash_bindings']:
  path=Path(item['path']) if Path(item['path']).is_absolute() else ROOT/item['path'];assert path.is_file() and sha(path)==item['sha256'],item['path']
 relative=str(EVIDENCE.relative_to(ROOT)).replace('\\','/');head,fingerprint,count=fingerprint_excluding(relative);assert head==r['candidate_binding']['git_head'];assert fingerprint==r['candidate_binding']['pre_record_candidate_tree_fingerprint'];assert count==r['candidate_binding']['pre_record_candidate_tree_path_count']
 assert r['common_gate']['checks_in_order']==base.COMMON_CHECKS;checks=r['common_gate']['checks'];assert [x['check'] for x in checks]==base.COMMON_CHECKS;assert all(x['pass'] for x in checks[:11]);assert checks[11]['pass'] is False;assert r['common_gate']['failed_checks']==['explicit_hash_bound_human_approval'];assert r['common_gate']['verdict']=='AWAITING_EXPLICIT_HASH_BOUND_HUMAN_APPROVAL'
 assert r['local_vision_gate']['pass'] is True and r['local_vision_gate']['confidence']>=0.8;assert r['independent_visual_adjudication']['pass'] is True;assert r['human_approval']['present'] is False and r['human_approval']['approved'] is False;assert r['status_effect']['task_11_8_4a_complete'] is False and r['status_effect']['task_11_8_5']=='BLOCKED'
 art=base.inspect_artifact();assert art['durable_material_present'] and art['external_image_uris']==[] and art['external_buffer_uris']==[]
 print('PASS Task 11.8.4a additional-03 approval-candidate validation');print('  evidence_sha256:',sha(EVIDENCE));print('  candidate_fingerprint:',fingerprint);print('  artifact_sha256:',sha(ARTIFACT));print('  preview_sha256:',r['selected_preview']['sha256']);print('  non_human_checks: 11/11 PASS');print('  local_vision: PASS confidence',r['local_vision_gate']['confidence']);print('  human_approval: FALSE; Task 11.8.5 BLOCKED')
if __name__=='__main__':main()
