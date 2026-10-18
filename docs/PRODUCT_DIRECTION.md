# Product direction and delivery plan

Updated: 2026-10-16. Audience: individual Suno creators, initially English-speaking.

## Promise and primary workflow

Turn a creator's song into an editable lyric video they can confidently publish.
The main path is Import song → Check lyrics → Design video → Export/download.
The first release supports complete songs as well as short promotional excerpts.
Publishing integrations, a social matrix, automated prospecting, 3D rhythm games
and new AI video-generation models are outside the first paid release.

## Product objects and navigation

- Song: the user's musical work. Suno identity is owner + provider + song UUID.
- Version: an imported/aligned task with its own lyric snapshot and editable data.
- Export: a rendered video derived from a specific version. Multiple ratios and
  clips belong to the same song, with durable access through My Exports.
- Background task: operational status, not a competing top-level work object.

Primary navigation is My songs and My Exports. Credit history, extension access
and account controls are secondary. Import defaults should work without knowing
separation, rhythm-analysis or backend configuration details.

## Phase 1 — song library (implemented in feat/song-library)

- One card per song, 12 per page, title search and recently updated/title sorting.
- Favorites and archive/restore, stored per user; archive never deletes media.
- Versions/history expand inside the song. Choosing the current editable version
  changes a personal pointer and does not trigger processing or charge credits.
- A failed/pending new import cannot displace the last usable editable version.
- View videos filters My Exports across all task versions of the selected song.
- Existing task IDs, URLs, media keys and accounting history stay valid. The new
  song_preferences table is created by init_db; there is no destructive migration.
- Unresolved legacy short links remain separate until their ordinary import flow
  resolves the song UUID. Titles are never identity, and library reads never fetch
  Suno pages, alignment files, stems or artwork.

This is an aggregate view over existing tasks, not yet a new source-of-truth Song
entity. Pagination/search apply after grouping across the owner's metadata, so
versions never split across pages. This avoids the old 50-task display cutoff but
still reads that owner's task metadata into memory; it is designed for an initial
personal library of tens to hundreds of songs, not a demonstrated million-row
search architecture. If usage requires it, introduce persisted Song/Version rows
and indexed database search behind the same API.

## Phase 2A — choosing and protecting versions (implemented)

- Both cloud editors use the same searchable song/version dialog with 12 songs
  per page. The current editable version is the default, and older version links
  remain usable. Opening the picker reads metadata, not every alignment or stem.
- Dashboard cards request private cover thumbnails and artist metadata separately;
  absent artwork falls back to initials. User-edited artwork and credits take
  precedence. Thumbnail links expire after 15 minutes; browser metadata caching
  lasts at most 12 minutes and is scoped to the account and version update time.
- Move to Trash hides a version from the library, import reuse and editor APIs.
  Restore makes saved data accessible again; it never restarts failed processing.
  Pending import/render reservations are returned once. Finished videos remain in
  My Exports, even when their lyric version is in Trash.
- Trash is recoverable storage, not space reclamation: no automatic expiry or
  permanent-purge UI is included. The legacy task DELETE API remains destructive
  for compatibility; the song library does not call it. Video deletion retains
  its existing independent confirmation and behavior.
- The new version_trash table is created by init_db without altering existing
  task columns. Deploy the backend before the frontend using these new routes.

## Phase 2B — editing and clip completion (completed)

1. **Non-Destructive Timing Anomaly Inspection**:
   - Automated detection in `src/editing_review.py` and `frontend/local/lyric_editor.js` covering timestamp overlaps, inverted intervals, compressed singing durations (<45ms line/word or <35ms/vocal unit), excessive intra-line gaps (>1.2s), stretched tail words (>3.5s occupying >72% of sentence duration), and aligner low-confidence tokens (`needs_review`, `unresolved_compound`).
   - Guarantees 100% non-destructive operation: valid singing timestamps are never silently rewritten.
   - UI features a persistent Timing Review Bar with severity counts, Prev/Next navigation across flagged lines, "Flagged Only" filter, and clickable diagnostic evidence cards jumping to specific words.

2. **Smart Excerpt Recommendation & Sentence Snapping**:
   - Multi-candidate promotional excerpt generation (`recommend_excerpt_candidates`) combining musical sections (Chorus prioritized with weight boost, Verse, Bridge) and lyric hook density.
   - Sentence boundary snapping (`snap_excerpt_to_sentence_bounds`): snaps export start/end times strictly to full sentence boundaries (`lines[start].start` to `lines[end].end`), eliminating mid-sentence cuts.
   - Frontend provides smart excerpt cards, sentence selectors, step buttons (`-1/+1 Sent`), automatic sentence snapping checkbox, and clip auditioning (`▶ Audition Clip`).

3. **Curated Themes & 9:16 Portrait Safe Areas**:
   - Enforced 9:16 social portrait safe area (`14%–76%` vertical bounds, `8%–86%` horizontal bounds) in ASS generation (`src/subtitle.py`) and Motion layout (`frontend/motion/src/song-layout.ts`), protecting lyrics from TikTok/Reels/Shorts top search chrome, bottom captions/scrub bars, and right-side social action rails.
   - Curated 5 complete visual themes (`apple_white_ambient`, `cyber_neon_bounce`, `amber_vinyl_classic`, `midnight_ktv_duet`, `emerald_minimal_black`) setting coordinated background, template, palette, and typography in one click.
   - Live real-time safe area preview canvas in the export dialog with toggleable guide lines.

4. **Empirical 720p vs 1080p Render Profiling**:
   - Empirical measurements on a 15.0s portrait video clip (`Road Closed, Door Open`, blurred ambient cover glow + Apple Music scroll):
     - **720p Fast Draft (720×1280)**: 4.47s elapsed render time, 0.72MB file size (751,202 bytes), 306.16MB peak RSS memory.
     - **1080p Full HD (1080×1920)**: 5.97s elapsed render time, 1.07MB file size (1,120,862 bytes), 312.52MB peak RSS memory.
     - **Empirical speedup**: 720p draft renders ~1.34× faster with 33.0% smaller storage payload, making it ideal for rapid mobile drafts before final 1080p publishing.
     - Export dialog provides a Resolution Profile selector (`1080p` vs `720p`) properly scaling typography, ASS coordinates, and FFmpeg output.

## Phase 3 — paid beta gates (Draft / In Progress)

Phase 3 implements foundational gates for account lifecycle, queue admission, storage policy, and entitlement enforcement. **Commercial billing is currently deferred (pricing remains 0)** while focusing on core continuous creation and export experiences.

1. **Payment Model & Mock Sandbox Hardening (Draft / Pre-Gateway)**:
   - Implemented `src/payments.py` with top-up packages (`starter`: 20 credits/$4.99, `creator`: 60 credits/$12.99, `studio`: 200 credits/$39.99).
   - Checkout endpoints with client-provided `idempotency_key` prevent duplicate order records.
   - Verified, idempotent webhook callback structure (`/api/payments/webhook/{provider}`) with HMAC-SHA256 signature checking.
   - **Hardened**: `/api/payments/mock-complete/{order_id}` is gated behind explicit `M2V_ALLOW_MOCK_PAYMENTS="true"`, authentication, and strict order ownership checks (preventing arbitrary credit minting in production).
   - Packages API reports `pricing_live: False` and `billing_status: beta_preview`.
   - *Pending before live sales*: Production webhook credentials and hosted checkout flows for Stripe / Alipay / WeChat.

2. **Unified Entitlements & Export Resilience**:
   - Unified credit reservations across lyric video export (`src/export_jobs.py`) and motion cloud export (`src/motion_cloud.py`, `src/motion_api.py`).
   - Export pricing settings default to 0 during beta (`LYRIC_EXPORT_CREDITS = 0`, `MOTION_EXPORT_CREDITS = 0`) to keep all exports free.
   - **Hardened**: Motion export error handling cleans up reservations and queued job slots upon failure, preventing render queue deadlock.
   - **Hardened**: ASS subtitle coordinate rendering adaptively scales for 720p, 1080p, and 4K, preventing subtitles from rendering out of canvas.

3. **Strict Owner Isolation**:
   - Zero cross-account data leakage across songs, versions, exports, order histories, storage accounting, and scoped download tickets. Foreign requests receive 403/404.

4. **Storage Accounting & Deduplicated Retention**:
   - `src/storage_accounting.py` exposes `/api/storage/accounting` reporting breakdown of video, deduplicated audio, trash, and metadata bytes, quota usage, and counts.
   - Versions of the same song sharing audio stems are deduplicated rather than inflated.
   - `check_storage_quota` protects the server against storage exhaustion upon new imports.
   - Visible retention policy guarantees permanent retention for active songs, stems, and version histories (`silent_deletion_forbidden: True`).

5. **Queue Admission & Database Backups**:
   - `src/queue_limiter.py` enforces synchronized per-user concurrency (`MAX_CONCURRENT_RENDERS_PER_USER = 2`, returning HTTP 429) and global capacity protection (`MAX_GLOBAL_CONCURRENT_RENDERS = 4`, returning HTTP 503).
   - Concurrency limits unified across both lyric video rendering and active Motion Studio rendering.
   - `src/backup.py` implements point-in-time SQLite database snapshotting with SHA-256 checksums and `PRAGMA integrity_check` verification.
   - **Hardened**: `/api/admin/backup` strictly requires verified administrator authorization (`M2V_ADMIN_USERS`). PostgreSQL backups require the system `pg_dump` CLI and do not emit misleading mock manifests.

6. **Automated Verification**:
   - Verified across end-to-end integration test suites (`test_phase3_paid_beta.py`, `test_phase2b_editing.py`, `test_credits.py`, frontend node tests, and motion test suites).


## Evidence and release metrics

Track time to first exported video, import/export failure rate, manual timing
corrections needed per excerpt, return usage and subsequent exports. Establish a
baseline before choosing numeric targets. Use at least 20 varied songs and invite
10 creators to complete the workflow. Automated tests do not substitute for
listening to alignment, visual review or production payment/storage validation.

## Phase 1 acceptance

Same Suno UUID with short/full URLs and changed lyrics appears as one song;
same titles with different UUIDs stay separate. Search finds old-version titles;
page 6 can reach a 61st song. Archive is reversible, preferences are isolated,
a deleted preferred version falls back safely, and filtering videos never exposes
another owner's records. No library operation downloads audio or consumes credits.
