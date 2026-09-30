# Motion Studio renderer

Three.js scene and pdoom-derived post-processing, shared by preview and MP4 export. See `../../docs/motion-studio-director.md` for the versioned director contract and user flow.

Node 22: `npm ci`, `npm run check`, `npm test`, `npm run build`.

Set `M2V_PYTHON` to the project Python interpreter and run `npm run dev` to start the unified Python editor (default port 8768). Alternatively start `python -m src.local_editor` from the repository after building.

`npm run render -- job.json output.mp4` runs only the offline render worker. A job contains project, options, audioPath, start and length; use the Studio API to validate and snapshot a saved director plan before rendering. Chrome/Chromium and FFmpeg are required; `CHROME_PATH` overrides the platform default.

Generated bundles are ignored and rebuilt in CI/Docker. Fonts use system Chinese fallbacks; cross-platform font pinning is not implemented yet. See `src/vendor/pdoom/README.md` for source provenance and the MIT license.
