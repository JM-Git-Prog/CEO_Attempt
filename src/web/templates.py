"""HTML template for the Living Room chat UI with embedded 3D viewer."""


def get_index_html() -> str:
    return INDEX_HTML


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Living Room</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: #0a0a0f; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }
        .header { padding: 12px 20px; border-bottom: 1px solid #1a1a2e; background: #0d0d14; display: flex; align-items: center; }
        .header h1 { font-size: 1.2rem; font-weight: 300; color: #ffb347; }
        .content { flex: 1; display: flex; overflow: hidden; }
        .chat-panel { width: 100%; max-width: 900px; margin: 0 auto; display: flex; flex-direction: column; }
        .messages { flex: 1; overflow-y: auto; padding: 16px; }
        .message { margin-bottom: 12px; padding: 10px 14px; border-radius: 8px; max-width: 90%; line-height: 1.4; font-size: 0.9rem; }
        .message.system { background: #1a1a2e; color: #9090a0; max-width: 100%; border-left: 3px solid #ffb347; }
        .message.user { background: #1e3a5f; margin-left: auto; color: #d0e0f0; }
        .message.ai { background: #1a2e1a; color: #c0e0c0; }
        .message.progress { background: #2a2a1a; color: #e0d080; font-size: 0.8rem; font-family: monospace; }
        .canon-image { margin: 12px 0; text-align: center; }
        .canon-image img { max-width: 100%; border-radius: 6px; border: 1px solid #333; }
        .canon-image .actions { margin-top: 10px; display: flex; gap: 8px; justify-content: center; }
        .btn { padding: 7px 16px; border: none; border-radius: 5px; cursor: pointer; font-size: 0.85rem; font-weight: 500; }
        .btn-approve { background: #2ecc71; color: #000; }
        .btn-approve:hover { background: #27ae60; }
        .btn-reject { background: #444; color: #e0e0e0; border: 1px solid #666; }
        .btn-download { background: #ffb347; color: #000; font-weight: 600; text-decoration: none; display: inline-block; padding: 8px 18px; border-radius: 5px; margin-top: 8px; }
        .input-area { padding: 12px; border-top: 1px solid #1a1a2e; }
        .input-row { display: flex; gap: 8px; }
        .input-row textarea { flex: 1; background: #141420; border: 1px solid #2a2a3e; color: #e0e0e0; padding: 10px 12px; border-radius: 6px; font-size: 0.9rem; font-family: inherit; resize: none; height: 50px; outline: none; }
        .input-row textarea:focus { border-color: #ffb347; }
        .input-row textarea::placeholder { color: #555; }
        .input-row button { padding: 10px 20px; background: #ffb347; color: #000; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; }
        .input-row button:disabled { background: #444; color: #888; cursor: not-allowed; }
        .scene-info { background: #141420; border: 1px solid #2a2a3e; border-radius: 6px; padding: 12px; margin: 8px 0; font-size: 0.8rem; }
        .scene-info h3 { color: #ffb347; margin-bottom: 6px; font-size: 0.9rem; }
        .scene-info .detail { margin-bottom: 3px; color: #a0a0b0; }
        .scene-info .detail strong { color: #d0d0e0; }
        .loading { display: inline-block; width: 10px; height: 10px; border: 2px solid #ffb347; border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; margin-right: 6px; }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div class="header"><h1>The Living Room</h1><p style="font-size:0.8rem;color:#666;margin-left:12px">Describe any interior. Walk into it.</p></div>
    <div class="content">
        <div class="chat-panel fullwidth" id="chatPanel">
            <div class="messages" id="messages">
                <div class="message system">Describe the room you want to build. Once you approve the canon image, the 3D world will render right here in the chat.</div>
            </div>
            <div class="input-area"><div class="input-row">
                <textarea id="input" placeholder="A 1950s diner counter with four chrome stools, warm pendant lamp, rain on the window..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}"></textarea>
                <button id="sendBtn" onclick="send()">Build</button>
            </div></div>
        </div>
    </div>

    <!-- Three.js from CDN -->
    <script src="https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.169.0/examples/js/controls/OrbitControls.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.169.0/examples/js/loaders/GLTFLoader.js"></script>

    <script>
        let sessionId = null;
        const messages = document.getElementById('messages');
        const input = document.getElementById('input');
        const sendBtn = document.getElementById('sendBtn');

        function addMessage(type, content) {
            const div = document.createElement('div');
            div.className = 'message ' + type;
            div.innerHTML = content;
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
            return div;
        }
        function addProgress(text) { return addMessage('progress', '<span class="loading"></span>' + text); }

        async function send() {
            const desc = input.value.trim();
            if (!desc) return;
            input.value = '';
            sendBtn.disabled = true;
            addMessage('user', desc);
            if (!sessionId) { const r = await fetch('/api/session', {method:'POST'}); sessionId = (await r.json()).session_id; }
            const p = addProgress('Interpreting and generating canon image...');
            try {
                const r = await fetch(`/api/session/${sessionId}/describe`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({description:desc})});
                const data = await r.json();
                p.remove();
                if (data.concept) {
                    const c = data.concept;
                    addMessage('ai', `<div class="scene-info"><h3>Scene Concept</h3><div class="detail"><strong>Era:</strong> ${c.era}</div><div class="detail"><strong>Mood:</strong> ${c.mood}</div><div class="detail"><strong>Lighting:</strong> ${c.lighting_notes}</div></div>`);
                }
                if (data.canon_image) {
                    const d = document.createElement('div'); d.className = 'canon-image';
                    d.innerHTML = `<img src="${data.canon_image}" /><div class="actions"><button class="btn btn-approve" onclick="approveImage()">Approve & Build World</button><button class="btn btn-reject" onclick="rejectImage()">Reject & Revise</button></div>`;
                    messages.appendChild(d); messages.scrollTop = messages.scrollHeight;
                }
            } catch(e) { p.remove(); addMessage('system', 'Error: '+e.message); }
            sendBtn.disabled = false;
        }

        async function approveImage() {
            const p = addProgress('Building 3D world...');
            try {
                const r = await fetch(`/api/session/${sessionId}/approve`, {method:'POST'});
                const data = await r.json();
                p.remove();

                if (data.scene_graph) {
                    // Build the 3D scene inline - right here in the chat
                    const viewerDiv = document.createElement('div');
                    viewerDiv.style.cssText = 'width:100%;height:500px;border-radius:8px;overflow:hidden;margin:12px 0;border:1px solid #2a2a3e;position:relative;';
                    const viewerCanvas = document.createElement('canvas');
                    viewerCanvas.style.cssText = 'width:100%;height:100%;display:block;';
                    viewerDiv.appendChild(viewerCanvas);
                    const controlsHint = document.createElement('div');
                    controlsHint.style.cssText = 'position:absolute;bottom:10px;left:10px;background:rgba(10,10,15,0.85);padding:8px 12px;border-radius:5px;font-size:0.7rem;color:#999;border:1px solid #2a2a3e;';
                    controlsHint.innerHTML = '<b style="color:#ffb347">Drag</b> orbit &nbsp; <b style="color:#ffb347">Scroll</b> zoom &nbsp; <b style="color:#ffb347">Right-drag</b> pan';
                    viewerDiv.appendChild(controlsHint);
                    messages.appendChild(viewerDiv);
                    messages.scrollTop = messages.scrollHeight;
                    // Render 3D into this canvas
                    buildInlineViewer(viewerCanvas, data.scene_graph);
                }
            } catch(e) { p.remove(); addMessage('system', 'Error: '+e.message); }
        }

        async function rejectImage() {
            const feedback = prompt('What should be changed?');
            if (!feedback) return;
            addMessage('user', 'Revision: ' + feedback);
            const p = addProgress('Regenerating...');
            try {
                const r = await fetch(`/api/session/${sessionId}/reject`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({feedback})});
                const data = await r.json();
                p.remove();
                if (data.canon_image) {
                    const d = document.createElement('div'); d.className = 'canon-image';
                    d.innerHTML = `<img src="${data.canon_image}?t=${Date.now()}" /><div class="actions"><button class="btn btn-approve" onclick="approveImage()">Approve & Build World</button><button class="btn btn-reject" onclick="rejectImage()">Reject & Revise</button></div>`;
                    messages.appendChild(d); messages.scrollTop = messages.scrollHeight;
                }
            } catch(e) { p.remove(); addMessage('system', 'Error: '+e.message); }
        }

        // ========== THREE.JS 3D VIEWER (INLINE) ==========

        function buildInlineViewer(canvas, sceneGraph) {
            const rect = canvas.parentElement.getBoundingClientRect();
            const w = rect.width || 800;
            const h = rect.height || 500;

            const scene = new THREE.Scene();
            scene.background = new THREE.Color(0x0a0a0f);

            const cam = new THREE.PerspectiveCamera(75, w / h, 0.1, 100);
            const room = sceneGraph.room;
            const hd = room.depth / 2;
            cam.position.set(0, 2.0, hd + 2);

            const rend = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
            rend.setSize(w, h);
            rend.setPixelRatio(window.devicePixelRatio);
            rend.shadowMap.enabled = true;
            rend.shadowMap.type = THREE.PCFSoftShadowMap;
            rend.toneMapping = THREE.ACESFilmicToneMapping;
            rend.toneMappingExposure = 1.0;

            const ctrl = new THREE.OrbitControls(cam, canvas);
            ctrl.enableDamping = true;
            ctrl.dampingFactor = 0.05;
            ctrl.target.set(0, 1, 0);

            // Floor
            const floorMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(room.floor_material.base_color), roughness: room.floor_material.roughness, metalness: room.floor_material.metallic });
            const floor = new THREE.Mesh(new THREE.BoxGeometry(room.width, 0.1, room.depth), floorMat);
            floor.position.set(0, -0.05, 0);
            floor.receiveShadow = true;
            scene.add(floor);

            // Ceiling
            const ceilMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(room.ceiling_material.base_color), roughness: room.ceiling_material.roughness });
            const ceil = new THREE.Mesh(new THREE.BoxGeometry(room.width, 0.1, room.depth), ceilMat);
            ceil.position.set(0, room.height + 0.05, 0);
            scene.add(ceil);

            // Walls
            const wallMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(room.wall_material.base_color), roughness: room.wall_material.roughness, side: THREE.DoubleSide });
            const hw = room.width / 2;
            const hh = room.height / 2;
            const hdp = room.depth / 2;
            scene.add(Object.assign(new THREE.Mesh(new THREE.BoxGeometry(room.width, room.height, 0.15), wallMat), {position: new THREE.Vector3(0, hh, hdp+0.075)}));
            scene.add(Object.assign(new THREE.Mesh(new THREE.BoxGeometry(room.width, room.height, 0.15), wallMat), {position: new THREE.Vector3(0, hh, -(hdp+0.075))}));
            scene.add(Object.assign(new THREE.Mesh(new THREE.BoxGeometry(0.15, room.height, room.depth), wallMat), {position: new THREE.Vector3(hw+0.075, hh, 0)}));
            scene.add(Object.assign(new THREE.Mesh(new THREE.BoxGeometry(0.15, room.height, room.depth), wallMat), {position: new THREE.Vector3(-(hw+0.075), hh, 0)}));

            // Objects
            sceneGraph.objects.forEach(obj => {
                let geo;
                if (obj.primitive_shape === 'cylinder') geo = new THREE.CylinderGeometry(obj.dimensions.x/2, obj.dimensions.x/2, obj.dimensions.y, 16);
                else if (obj.primitive_shape === 'sphere') geo = new THREE.SphereGeometry(Math.max(obj.dimensions.x,obj.dimensions.y,obj.dimensions.z)/2, 16, 16);
                else geo = new THREE.BoxGeometry(obj.dimensions.x, obj.dimensions.y, obj.dimensions.z);

                const mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(obj.material.base_color), roughness: obj.material.roughness, metalness: obj.material.metallic });
                const mesh = new THREE.Mesh(geo, mat);
                mesh.position.set(obj.position.x, obj.position.y + obj.dimensions.y/2, obj.position.z);
                mesh.rotation.y = (obj.rotation.y || 0) * Math.PI / 180;
                mesh.castShadow = true;
                mesh.receiveShadow = true;
                scene.add(mesh);
            });

            // Doors
            (sceneGraph.doors || []).forEach(door => {
                const mesh = new THREE.Mesh(new THREE.BoxGeometry(door.width, door.height, 0.04), new THREE.MeshStandardMaterial({color:0x644228, roughness:0.7}));
                mesh.position.set(door.position.x, door.height/2, door.position.z);
                mesh.castShadow = true;
                scene.add(mesh);
            });

            // Lights
            scene.add(new THREE.AmbientLight(new THREE.Color(sceneGraph.ambient_color), (sceneGraph.ambient_energy || 0.3) * 2));
            (sceneGraph.lights || []).forEach(light => {
                let l;
                const c = new THREE.Color(light.color);
                if (light.light_type === 'point') { l = new THREE.PointLight(c, light.intensity*2, light.range_meters); l.castShadow = true; }
                else if (light.light_type === 'directional') { l = new THREE.DirectionalLight(c, light.intensity); l.castShadow = true; }
                else if (light.light_type === 'spot') { l = new THREE.SpotLight(c, light.intensity*2, light.range_meters, (light.spot_angle_deg||45)*Math.PI/180); l.castShadow = true; }
                if (l) { l.position.set(light.position.x, light.position.y, light.position.z); scene.add(l); }
                // Light bulb indicator
                const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.06,8,8), new THREE.MeshBasicMaterial({color:c}));
                bulb.position.set(light.position.x, light.position.y, light.position.z);
                scene.add(bulb);
            });

            // Animate
            function loop() {
                requestAnimationFrame(loop);
                ctrl.update();
                rend.render(scene, cam);
            }
            loop();

            // Handle resize
            const ro = new ResizeObserver(() => {
                const r2 = canvas.parentElement.getBoundingClientRect();
                cam.aspect = r2.width / r2.height;
                cam.updateProjectionMatrix();
                rend.setSize(r2.width, r2.height);
            });
            ro.observe(canvas.parentElement);
        }

        input.focus();
    </script>
</body>
</html>"""
