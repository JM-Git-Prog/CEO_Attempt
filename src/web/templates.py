"""HTML template for the Living Room chat UI."""


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
        .header { padding: 20px 30px; border-bottom: 1px solid #1a1a2e; background: #0d0d14; }
        .header h1 { font-size: 1.4rem; font-weight: 300; color: #ffb347; }
        .header p { font-size: 0.8rem; color: #666; margin-top: 4px; }
        .main { flex: 1; display: flex; flex-direction: column; max-width: 900px; width: 100%; margin: 0 auto; padding: 20px; overflow-y: auto; }
        .messages { flex: 1; overflow-y: auto; padding-bottom: 20px; }
        .message { margin-bottom: 16px; padding: 12px 16px; border-radius: 8px; max-width: 80%; line-height: 1.5; }
        .message.system { background: #1a1a2e; color: #9090a0; max-width: 100%; font-size: 0.85rem; border-left: 3px solid #ffb347; }
        .message.user { background: #1e3a5f; margin-left: auto; color: #d0e0f0; }
        .message.ai { background: #1a2e1a; color: #c0e0c0; }
        .message.progress { background: #2a2a1a; color: #e0d080; font-size: 0.85rem; font-family: monospace; }
        .canon-image { margin: 16px 0; text-align: center; }
        .canon-image img { max-width: 100%; border-radius: 8px; border: 2px solid #333; }
        .canon-image .actions { margin-top: 12px; display: flex; gap: 10px; justify-content: center; }
        .btn { padding: 8px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 0.9rem; font-weight: 500; }
        .btn-approve { background: #2ecc71; color: #000; }
        .btn-approve:hover { background: #27ae60; }
        .btn-reject { background: #444; color: #e0e0e0; border: 1px solid #666; }
        .btn-reject:hover { background: #555; }
        .btn-download { background: #ffb347; color: #000; font-weight: 600; text-decoration: none; display: inline-block; padding: 10px 24px; border-radius: 6px; }
        .btn-download:hover { background: #ffa020; }
        .input-area { padding: 16px 0; border-top: 1px solid #1a1a2e; }
        .input-row { display: flex; gap: 10px; }
        .input-row textarea { flex: 1; background: #141420; border: 1px solid #2a2a3e; color: #e0e0e0; padding: 12px 16px; border-radius: 8px; font-size: 0.95rem; font-family: inherit; resize: none; height: 60px; outline: none; }
        .input-row textarea:focus { border-color: #ffb347; }
        .input-row textarea::placeholder { color: #555; }
        .input-row button { padding: 12px 24px; background: #ffb347; color: #000; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; }
        .input-row button:hover { background: #ffa020; }
        .input-row button:disabled { background: #444; color: #888; cursor: not-allowed; }
        .scene-info { background: #141420; border: 1px solid #2a2a3e; border-radius: 8px; padding: 16px; margin: 12px 0; font-size: 0.85rem; }
        .scene-info h3 { color: #ffb347; margin-bottom: 8px; font-weight: 500; }
        .scene-info .detail { margin-bottom: 4px; color: #a0a0b0; }
        .scene-info .detail strong { color: #d0d0e0; }
        .loading { display: inline-block; width: 12px; height: 12px; border: 2px solid #ffb347; border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; margin-right: 8px; }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div class="header"><h1>The Living Room</h1><p>Describe any interior. Walk into it.</p></div>
    <div class="main">
        <div class="messages" id="messages">
            <div class="message system">Describe the room you want to build. The AI will interpret your description, generate a photorealistic image for approval, and construct a complete 3D world you can walk through.</div>
        </div>
        <div class="input-area"><div class="input-row">
            <textarea id="input" placeholder="A 1950s diner counter with four chrome stools, warm pendant lamp, rain on the window..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}"></textarea>
            <button id="sendBtn" onclick="send()">Build</button>
        </div></div>
    </div>
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
                    addMessage('ai', `<div class="scene-info"><h3>Scene Concept</h3><div class="detail"><strong>Era:</strong> ${c.era}</div><div class="detail"><strong>Mood:</strong> ${c.mood}</div><div class="detail"><strong>Palette:</strong> ${c.palette}</div><div class="detail"><strong>Lighting:</strong> ${c.lighting_notes}</div></div>`);
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
            const p = addProgress('Building world... generating assets, physics, lighting...');
            try {
                const r = await fetch(`/api/session/${sessionId}/approve`, {method:'POST'});
                const data = await r.json();
                p.remove();
                addMessage('ai', `<div class="scene-info"><h3>Your world is ready!</h3><p style="margin:8px 0;color:#c0e0c0">Godot project generated with physics, lighting, and first-person controller. Download it, open in Godot 4, press Play.</p><a href="${data.download_url}" class="btn-download">Download Godot Project</a></div>`);
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
        input.focus();
    </script>
</body>
</html>"""
