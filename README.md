---
title: Suno2MV API
emoji: 🎵
colorFrom: indigo
colorTo: purple
sdk: gradio
app_file: app.py
pinned: false
---

# M2V — Editable lyric videos for music creators

Turn your song into a lyric video: **My Songs → Lyric Editor → Motion Design → My Exports**.

[Web workspace](https://mv.fovea.si) · [CI](https://github.com/AFeiYA/m2v/actions) · [Documentation](docs/README.md)

## Supported product

- Import a published Suno song, separate vocals/instrumental and align its lyrics.
- Review timing warnings and edit sentence/word boundaries without replacing lyrics.
- Save lyric timing, song credits, artwork and visual design.
- Export Apple-style portrait, two-line landscape karaoke or kinetic typography,
  as a full song or selected excerpt in the export matrix.
- Attempt browser encoding first and retain server rendering as a fallback.
  Encoding speed depends on the device, format and song duration.
- Keep exported MP4s in the owner-scoped My Exports library for later download
  or explicit deletion. Credits are settled against successful publication.

Publishing integrations, generative-video storyboards, Motion Lab, Rhythm Studio
and the older player remain experimental/legacy code. They are not the first paid
release's product promise. See [module boundaries](docs/PROJECT_STRUCTURE.md).

## Development

Python 3.10+ (CI uses 3.10), Node 22 and FFmpeg/ffprobe are required. Copy
`.env.example` to a private `.env` and configure your development environment.
Use a development database/storage namespace; do not test against production data.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install pytest pytest-cov ruff
cd frontend/motion
npm ci
npm run check
npm test
npm run build
```

From the repository root, run the local editor with:

```sh
.venv/bin/python -m src.local_editor --port 8000
```

Use localhost/127.0.0.1 or HTTPS for browser media APIs. `app.py` is the production
Gradio entry point; `src.api_server` also supports standalone API development.

## Build and test

- `frontend/motion/src/`: editable TypeScript/React render and studio sources.
- `npm run build:pages`: browser bundles only; `npm run build`: browser and server
  Remotion bundles. CI verifies and distributes the assets used by both deployments.
- `frontend/local/motion/*.js`: tracked generated browser assets, rebuilt from source.
- Python dependencies: `requirements.txt` is the current CI/Gradio install path;
  `pyproject.toml` and `uv.lock` support package/developer installs. Do not update
  one dependency path without checking the other. Historical lockfiles are archived.
- [Testing guide](tests/README.md) distinguishes synthetic CI, opt-in real rendering
  and private local media/account tests.

## Operations

[Deployment](DEPLOY.md) · [Product direction](docs/PRODUCT_DIRECTION.md) ·
[Billing](docs/LEMON_SQUEEZY_BILLING.md) · [Storage and rendering](docs/RENDER_ADMISSION_AND_STORAGE.md)

Firebase handles sign-in. SQL stores application records and the credit ledger;
private object storage holds media. Prices and provider secrets belong on the
backend. Never commit `.env`, login profiles, databases, source songs or exports.

Original plans and deployment examples are preserved under `docs/archive/`.
They describe earlier iterations and are not current operating instructions.
