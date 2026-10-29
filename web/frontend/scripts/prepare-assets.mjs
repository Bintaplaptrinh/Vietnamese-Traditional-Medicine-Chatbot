import { mkdir, copyFile, cp } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const root = new URL('../', import.meta.url);
const publicDir = new URL('public/', root);
await mkdir(new URL('legacy/', publicDir), { recursive: true });
await cp(new URL('assets/', root), new URL('assets/', publicDir), { recursive: true });
for (const file of ['app.js', 'graph.js', 'graph-renderer.js']) {
  await copyFile(new URL(file, root), new URL(`legacy/${file}`, publicDir));
}
for (const [source, target] of [
  ['node_modules/marked/lib/marked.umd.js', 'marked.js'],
  ['node_modules/dompurify/dist/purify.min.js', 'purify.js'],
]) await copyFile(new URL(source, root), new URL(`legacy/${target}`, publicDir));
console.log(`Prepared local browser assets in ${fileURLToPath(publicDir)}`);
