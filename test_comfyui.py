"""Test ComfyUI integration"""
import asyncio
import os
os.environ['COMFYUI_ENABLED'] = '1'

from src.pipeline import WorldBuilder

async def test():
    b = WorldBuilder()
    await b.step_interpret('A cozy living room with a couch')
    await b.step_generate_image()
    print('Image:', b.session.canon_image_path)

asyncio.run(test())
