import { readdir } from 'fs/promises';
import { join, dirname } from 'path';
import { fileURLToPath, pathToFileURL } from 'url';
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
/**
 * Discover and load all tools from the tools directory
 */
export async function discoverTools() {
    const toolsDir = join(__dirname, 'tools');
    const files = await readdir(toolsDir);
    // Filter for .js files (production) or .ts files (development)
    // Exclude test files and declaration files
    const toolFiles = files.filter((file) => (file.endsWith('.js') || file.endsWith('.ts')) &&
        !file.includes('.test.') &&
        !file.endsWith('.d.ts'));
    const tools = [];
    for (const file of toolFiles) {
        const toolPath = join(toolsDir, file);
        // Windows fix: ESM import() requires a file:// URL, not a raw c:\ path.
        const module = await import(pathToFileURL(toolPath).href);
        // Check if module exports tool metadata
        if (module.toolDefinition) {
            tools.push(module.toolDefinition);
        }
    }
    return tools;
}
//# sourceMappingURL=autoloader.js.map