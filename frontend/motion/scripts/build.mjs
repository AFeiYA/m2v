import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { bundle } from '@remotion/bundler';
import { build } from 'esbuild';

const root = fileURLToPath(new URL('../', import.meta.url));
await build({
  absWorkingDir: root, entryPoints: ['src/lab.ts', 'src/studio.ts', 'src/render-entry.ts'],
  outdir: '../local/motion', bundle: true, format: 'esm', target: 'es2022',
  minify: true, legalComments: 'linked', sourcemap: false,
});

const remotionOut = fileURLToPath(new URL('../../local/remotion', import.meta.url));
const mockEncoder = path.resolve(root, 'src/mock-encoder.ts');

await bundle({
  entryPoint: fileURLToPath(new URL('../src/remotion-root.tsx', import.meta.url)),
  outDir: remotionOut,
  onProgress: () => {},
  webpackOverride: (config) => {
    config.devtool = false;
    config.resolve = config.resolve || {};
    config.resolve.alias = {
      ...config.resolve.alias,
      '@mediabunny/aac-encoder': mockEncoder,
      '@mediabunny/flac-encoder': mockEncoder,
      '@mediabunny/mp3-encoder': mockEncoder,
    };
    return config;
  },
});

// 移除无头渲染不需要且会被 Hugging Face Git 判定为二进制拦截的无用资产
const favicon = path.join(remotionOut, 'favicon.ico');
if (fs.existsSync(favicon)) {
  fs.unlinkSync(favicon);
}
for (const file of fs.readdirSync(remotionOut)) {
  if (file.endsWith('.map') || file.endsWith('.ico')) {
    fs.unlinkSync(path.join(remotionOut, file));
  }
}

