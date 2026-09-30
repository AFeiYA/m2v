import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
await build({
  absWorkingDir: root, entryPoints: ['src/lab.ts', 'src/studio.ts', 'src/render-entry.ts'],
  outdir: '../local/motion', bundle: true, format: 'esm', target: 'es2022',
  minify: true, legalComments: 'linked', sourcemap: false,
});
