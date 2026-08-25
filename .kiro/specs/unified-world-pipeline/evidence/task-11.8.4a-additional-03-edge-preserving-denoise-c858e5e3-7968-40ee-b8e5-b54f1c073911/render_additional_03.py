"""Task 11.8.4a additional-03 renderer.

One focused hypothesis: preserve the prior geometry-derived normal/material rendering
and apply one bounded edge-preserving image-space denoise to remove residual stipple
without erasing broad upholstery, seams, footrest, or silhouette detail.
"""
from __future__ import annotations
import hashlib, importlib.util, json
from pathlib import Path
import cv2, numpy as np
from PIL import Image, ImageDraw, PngImagePlugin

BUNDLE=Path(__file__).resolve().parent; EVIDENCE_DIR=BUNDLE.parent
BASE_PATH=EVIDENCE_DIR/'task-11.8.4a-semantic-surface-recliner-cf5fd0f5-0ec5-4985-aa11-bc72dbd48637'/'render_semantic_surface_evidence.py'
OUTPUT=BUNDLE/'recliner-raw-crop_additional-03-edge-preserving-denoise-eight-panel.png'; RECORD=BUNDLE/'render-record.json'
ATTEMPT='additional-03'; METHOD='geometry-normal-edge-preserving-denoise-v1'
HYPOTHESIS='Preserve the corrected geometry-normal/material renderer and apply a bounded bilateral-plus-1px Gaussian image-space denoise inside the unchanged surface mask, targeting residual stipple while retaining broad topology, upholstery variation, semantic yaws, and silhouette.'

def load_base():
 spec=importlib.util.spec_from_file_location('semantic_base_for_03',BASE_PATH); assert spec and spec.loader; m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
base=load_base(); original_render=base.render_continuous_surface
ARTIFACT=base.ARTIFACT; EXPECTED_ARTIFACT_SHA256=base.EXPECTED_ARTIFACT_SHA256; MAX_RENDER_VERTICES=base.MAX_RENDER_VERTICES; one_geometry=base.one_geometry; surface_mask=base.surface_mask; mask_iou=base.mask_iou; derive_view_contract=base.derive_view_contract

def denoise(panel:Image.Image,mask:np.ndarray)->Image.Image:
 rgb=np.asarray(panel.convert('RGB'),dtype=np.uint8); filtered=cv2.bilateralFilter(rgb,d=9,sigmaColor=18.0,sigmaSpace=5.0); filtered=cv2.GaussianBlur(filtered,(0,0),sigmaX=1.0,sigmaY=1.0); out=rgb.copy(); out[mask]=filtered[mask]; return Image.fromarray(out,mode='RGB')
def render_continuous_surface(vertices,normals,colors,degrees,*,material):
 panel,mask=original_render(vertices,normals,colors,degrees,material=material); return denoise(panel,mask),mask
def sha256(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 base.BUNDLE=BUNDLE; base.OUTPUT=OUTPUT; base.RECORD=RECORD; base.render_continuous_surface=render_continuous_surface; base.main()
 image=Image.open(OUTPUT).convert('RGB'); draw=ImageDraw.Draw(image); draw.rectangle((0,0,image.width,base.HEADER-1),fill=(28,30,32)); draw.text((16,10),f'Task 11.8.4a {ATTEMPT} edge-preserving denoise | UUID {base.RECLINER_UUID}',fill=(250,250,250)); draw.text((16,34),'top: neutral topology | bottom: embedded durable material | same semantic views and neutral lights',fill=(205,210,215))
 record=json.loads(RECORD.read_text(encoding='utf-8')); contract=record['view_contract']; metadata=PngImagePlugin.PngInfo(); metadata.add_text('task','11.8.4a'); metadata.add_text('attempt',ATTEMPT); metadata.add_text('renderer',METHOD); metadata.add_text('view_contract_sha256',hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(',',':')).encode()).hexdigest()); metadata.add_text('semantic_yaws_degrees',json.dumps(contract['semantic_yaws_degrees'],sort_keys=True)); image.save(OUTPUT,format='PNG',optimize=True,pnginfo=metadata)
 record['schema']='unified-world-pipeline.task-11.8.4a.additional-render.v1'; record['attempt']=ATTEMPT; record['hypothesis']=HYPOTHESIS; record['renderer']={'method':METHOD,'source_geometry_normal_sigma_px':base.NORMAL_SMOOTH_SIGMA,'source_color_sigma_px':base.COLOR_SMOOTH_SIGMA,'bilateral_diameter_px':9,'bilateral_sigma_color':18.0,'bilateral_sigma_space_px':5.0,'final_gaussian_sigma_px':1.0,'same_semantic_views_and_lighting_for_rows':True}; record['before_geometry_stipple_score_by_panel']={'front':0.07384261519599865,'right':0.1788191768151688,'rear':0.14647007128210135,'left':0.17045079169327668}; record['output'].update({'path':base.relative(OUTPUT),'sha256':sha256(OUTPUT),'bytes':OUTPUT.stat().st_size}); RECORD.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'attempt':ATTEMPT,'preview':base.relative(OUTPUT),'preview_sha256':sha256(OUTPUT),'metrics':record['panels']},indent=2))
if __name__=='__main__':main()
