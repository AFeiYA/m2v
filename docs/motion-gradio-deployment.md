# Motion runtime: Gradio / ZeroGPU

The supported deployment is [Cloudflare Pages + HF Gradio](../DEPLOY.md).
Keep README metadata `sdk: gradio` and `app_file: app.py`; this cleanup does not
switch the Space SDK or the separation engine.

CI builds browser and server-render assets once, tests them and deploys that
snapshot to HF and Pages. Pages does not ship Remotion server bundles. Main uses
`/motion-studio` and the shared workspace; older underscore page names are not
production navigation. Vercel instructions are historical references in archive.

On HF startup, `prepare_motion_runtime()` checks the built files, Node >=22,
Chromium and FFmpeg. If required it installs the pinned/checksummed Linux Node
runtime in a user cache and installs npm production dependencies using the lockfile.
`CHROME_PATH` may select an installed browser. Local app.py startup does not perform
this installation unless `M2V_PREPARE_MOTION_RUNTIME=1` is set.

Application records use configured SQL; private media and design artifacts use
StorageBackend. Temporary workspace/cache files are restored from stored assets.
Server render requests use database admission/leases and ledger reservations;
this does not imply interrupted Chromium processes resume after a restart.
Browser encodes are separate: actual MP4 upload and verified archive precede
settlement; upload failure is retried without starting a server render.

Acceptance: inspect HF startup logs separately from GitHub sync success, open the
workspace, and check a short portrait/landscape video has audio and downloads from
My Exports after sign-in. CI real-render acceptance runs on relevant changes or
manual request, not every documentation commit. Never use private songs/account
cookies as normal CI fixtures. ZeroGPU eligibility and production capacity remain
platform/runtime concerns, not promises established by SDK metadata.
