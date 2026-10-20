# Product and code boundaries

## Supported workflow

My Songs → Lyric Editor → Motion Design → My Exports.
Sign-in, source assets, alignment, design saving, private downloads and the credit
ledger support this workflow. No database/assets are deleted by this cleanup.

| Responsibility | Main implementation |
| --- | --- |
| Workspace, library and exports UI | `frontend/index.html`, `dashboard.js`, `workspace*.js`, `studio-adapters.js` |
| Lyric timing editor | `frontend/local/index.html`, `lyric_editor.js`, `common.js` |
| Motion design | `frontend/motion/src/studio.ts`, layout/theme/render modules |
| Browser MP4 encoding | `webcodecs-exporter.ts`, `export-audio.ts` |
| Browser save request | `frontend/motion/src/browser-export.ts` |
| Validated browser MP4 archive + atomic charge | `src/motion_browser_exports.py` |
| Cloud render admission + ledger lifecycle | `src/motion_billing.py` |
| Existing render engine + private workspace adapter | `src/motion_api.py`, `motion_cloud.py` |
| Source import and alignment | `suno_fetch.py`, `worker.py`, `aligner.py`, `align/` |
| Shared persistence and ownership | `storage.py`, `models.py`, `song_library.py`, `export_library.py` |

Browser encoding failures may fall back to server rendering at the accepted price.
Upload/publication failures retry saving the same Blob/request, never rerender it.
Credit reservation kinds come from their stored ledger rows, never from matching
a configured price. No change to the alignment algorithm is part of this cleanup.

## Experimental and legacy features

Storyboards/generative video (`directors/`, `compilers/`, `video_providers/`),
Rhythm Studio, Motion Lab, public Gallery/player and social uploaders remain in
source with their current test coverage. They are not the primary navigation or
the paid-release promise. Existing direct URLs and API ownership guards remain;
removing a shortcut is not an authorization control.

The unused older Motion controller and page are archived in `docs/archive/frontend`.
`frontend/local/motion_studio.html` now links to the same canonical director page,
so compatibility filenames cannot drift into two implementations. Keep
`frontend/local`: it still supplies the actual editor pages and static assets.

## Builds and data

- Edit TypeScript sources, then rebuild; do not modify generated JS by hand.
- `build:pages` makes browser bundles; `build` also prepares Remotion server assets.
- Tracked browser bundles remain for local startup; CI supplies verified bundles
  and the ignored Remotion build to deployments. This policy is intentional.
- `requirements.txt` drives CI/Gradio, `pyproject.toml`/`uv.lock` remain a separate
  package install path. Consolidating their differing AI dependency constraints
  requires an environment-resolution migration, not an automatic version upgrade.
  The unused old `requirements.lock` is archived to avoid a third apparent source.
- Docker Compose and Dockerfile.web are alternative development/deployment paths;
  Vercel configurations are archived, not active production configuration.
- `.env`, input/output/work, caches, account profiles, databases and local media
  are excluded from Git. They are not automatically erased or moved.

## Safe next extractions

Large files are not split by line count alone. Move a tested responsibility at a
time: frontend export queue, then local editor route groups. Preserve existing
public imports/routes during extraction. Keep migrations, media keys and ledger
history intact; deleting old tasks or reprocessing audio is not code cleanup.

Physical storage accounting, cleanup of objects left by ambiguous DB commit
failures, direct object-store uploads for large browser videos and real-account
paid acceptance remain operational follow-ups. Do not describe them as solved by
moving source files.
