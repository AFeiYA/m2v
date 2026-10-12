// Pages serves the editor UI; MP4 rendering bundles are built on the backend.
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = fileURLToPath(new URL('../', import.meta.url));
await build({
  absWorkingDir: root,
  entryPoints: ['src/lab.ts', 'src/studio.ts'],
  outdir: '../local/motion',
  bundle: true,
  format: 'esm',
  target: 'es2022',
  minify: true,
  legalComments: 'linked',
  sourcemap: false,
});
