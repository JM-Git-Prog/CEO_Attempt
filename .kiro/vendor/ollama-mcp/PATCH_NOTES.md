# Vendored + patched `ollama-mcp` (Windows fix)

## Why this exists
The published `ollama-mcp` npm package (all versions 2.0.2 / 2.0.3 / 2.1.0) is broken
on Windows. Its `tools/list` handler calls `discoverTools()` in `dist/autoloader.js`,
which does a dynamic ESM `import()` on a raw Windows path:

```js
const toolPath = join(toolsDir, file);   // e.g. "c:\...\dist\tools\chat.js"
const module = await import(toolPath);    // THROWS on Windows
```

Node's ESM loader rejects raw drive-letter paths:

```
Only URLs with a scheme in: file, data, and node are supported by the default
ESM loader. On Windows, absolute paths must be valid file:// URLs. Received protocol 'c:'
```

Result: the server initializes but returns an error for `tools/list`, so Kiro
connects yet sees **zero tools** — the Ollama bridge is effectively dead even though
the local Ollama server itself works fine.

## The patch
File: `node_modules/ollama-mcp/dist/autoloader.js`

1. Import `pathToFileURL`:
   ```js
   import { fileURLToPath, pathToFileURL } from 'url';
   ```
2. Convert the path to a file:// URL before importing:
   ```js
   const module = await import(pathToFileURL(toolPath).href);
   ```

## How Kiro uses it
`.kiro/settings/mcp.json` → `mcpServers.ollama` runs this vendored copy directly with
`node` (NOT `npx -y ollama-mcp`, which would pull the unpatched package again):

```json
"command": "node",
"args": ["C:\\...\\.kiro\\vendor\\ollama-mcp\\node_modules\\ollama-mcp\\dist\\index.js"],
"env": { "OLLAMA_BASE_URL": "http://localhost:11434" }
```

## If you ever run `npm install` in this vendor dir again
It will overwrite the patched `autoloader.js`. Re-apply the two edits above.
(Upstream fix / issue: change line ~20 of `dist/autoloader.js` to use `pathToFileURL`.)

## Known minor quirk (not fixed here)
`ollama_chat` with the default `format:"json"` sometimes returns empty content `{}`.
Pass `format:"markdown"` for reliable text output. `ollama_list`, `ollama_embed`,
`ollama_generate`, etc. work in both formats.

Verified working: `tools/list` returns 14 tools; `ollama_list` returns the model
table; `ollama_chat` returns live model output.
