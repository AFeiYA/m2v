# Deployment: Cloudflare Pages + Hugging Face

This is the supported production path in `.github/workflows/ci.yml`.
Vercel configurations are historical references under `docs/archive/deployment/`;
they are not active deployment entry points.

## Responsibilities

- Cloudflare Pages serves the browser workspace and static assets at `mv.fovea.si`.
- The Gradio Space starts `app.py` and mounts the authenticated FastAPI APIs.
- Firebase authenticates users; application records and credits live in the
  configured SQL database. Private audio, alignment, artwork and video use the
  configured StorageBackend. Container-local files are caches, not durable storage.
- Browser rendering is attempted first; server rendering remains the fallback.
  Prices come from backend configuration, not frontend defaults.

## CI deployment

1. Changes to main run the frontend tests/build, backend tests and route checks.
   Relevant render changes also run real synthetic render acceptance. Manual
   dispatch can request rendering; ordinary documentation changes do not need it.
2. Both deploy jobs consume the same verified Motion assets. Do not hand-edit
   generated bundles in `frontend/local/motion/`.
3. HF deployment requires GitHub Secret `HF_TOKEN` and targets the Space declared
   in the workflow. CI creates an asset snapshot and replaces that Space's main
   branch; do not use the Space repository for independent application changes.
4. Pages deployment requires GitHub Secrets `CLOUDFLARE_API_TOKEN`,
   `CLOUDFLARE_ACCOUNT_ID`, and repository Variable `CLOUDFLARE_PAGES_PROJECT_NAME`.
   `scripts/prepare_pages.py` stages browser files, resolves page links and excludes
   source trees, tests, Node dependencies and backend Remotion bundles.
5. Configure backend secrets in the HF environment using `.env.example` as the
   reference. Never copy a local `.env`, database or account profile into Git.

The HF SDK remains **Gradio** (`sdk: gradio`, `app_file: app.py` in README).
It installs `requirements.txt` and `packages.txt`; the root Dockerfile is an
alternative container build, not the Gradio Space's startup configuration.

## Before enabling paid usage

- Configure durable SQL and private object storage. Verify fresh imports restore
  after a backend restart, including original audio, stems and alignment.
- Verify backend CORS and Firebase configuration for the actual frontend domain;
  see [Firebase authentication](docs/FIREBASE_AUTH.md).
- Configure Paddle with the three current subscription prices and run sandbox/live
  acceptance separately; see [billing policy](docs/BILLING_POLICY.md) and
  [Paddle go-live](docs/PADDLE_GO_LIVE_ZH.md). A successful code deploy does not
  mean merchant onboarding or payments are enabled.
- Run import → edit/save → export → My Exports → sign out/in → download with a
  test account. Verify a second account cannot access the first account's assets.
- Browser MP4s are uploaded before archive/credit settlement. The endpoint bounds
  files to 512 MiB; a proxy or hosting provider may impose a smaller limit. A failed
  save exposes Retry saving video and must not silently rerender or charge twice.

## Verification and rollback

Actions success confirms CI and deployment submission. Check HF build/startup logs
and the live site separately. The runtime checks Node, Chromium and FFmpeg before
serving server renders. See [runtime details](docs/motion-gradio-deployment.md).

Rollback by reverting the application commit and rerunning the normal pipeline.
Keep database migrations and stored asset keys compatible; never reset production
storage or credit history to roll back a UI change.
