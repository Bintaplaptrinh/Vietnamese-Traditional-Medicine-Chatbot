const path = require('node:path');
const fs = require('node:fs');
require('esbuild').buildSync({
  entryPoints: [path.join(__dirname, 'graph-gpu.js')],
  outfile: path.join(__dirname, '../assets/graph-gpu.min.js'),
  bundle: true,
  format: 'iife',
  globalName: 'GraphGPU',
  minify: true,
  target: 'es2020',
  legalComments: 'eof',
  nodePaths: (process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean),
});
const licenses = ['sigma', 'graphology', 'graphology-utils', 'graphology-layout-forceatlas2', 'events'].map(name => {
  let folder = path.dirname(require.resolve(name === 'events' ? 'events/' : name));
  while (!fs.existsSync(path.join(folder, 'package.json'))) {
    const parent = path.dirname(folder);
    if (parent === folder) throw new Error(`Cannot locate package metadata for ${name}`);
    folder = parent;
  }
  const filename = fs.readdirSync(folder).find(file => /^LICENSE(?:\.|$)/i.test(file));
  const version = JSON.parse(fs.readFileSync(path.join(folder, 'package.json'), 'utf8')).version;
  return `${name}@${version}\n${fs.readFileSync(path.join(folder, filename), 'utf8')}`;
});
fs.writeFileSync(path.join(__dirname, '../assets/graph-gpu-LICENSE.txt'), licenses.join('\n\n'));
