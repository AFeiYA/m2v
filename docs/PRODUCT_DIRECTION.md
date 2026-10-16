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

The legacy editor/Motion selectors still expose task versions. The library links
open a specific version; replacing both selectors with a shared searchable song
picker is a subsequent step. Library cards use initials until authenticated cover
thumbnails and author metadata can be added without loading audio or alignment.

## Phase 2 — editing and clip completion (next)

1. Shared searchable song/version picker in both editors; honor the library's
   current-version preference while preserving direct links to older versions.
2. Flag timing anomalies for review: compressed durations, excessive gaps and
   overlaps. Warnings need evidence and must not silently rewrite valid singing.
3. Recommend multiple excerpt candidates from existing sections, lyrics and music
   features. User auditions them and adjusts complete sentence boundaries.
4. Curate a small set of complete, previewable themes and portrait safe areas.
5. Profile actual 720p/1080p render time, memory and download behavior. Do not
   promise zero-cost upscaling or fixed render latency without measurements.

## Phase 3 — paid beta gates

- Real-account tests of import, edits, save, export, re-login and download.
- Owner isolation for songs, versions, exports and cache; failed operations refund
  once; restart/network failure never silently resubmits paid work.
- Unify entitlement/credit checks across every public export route before enabling
  nonzero export pricing; the ledger alone is not a completed payment product.
- Payment checkout, verified/idempotent callbacks, grants/refunds and order history.
- Storage accounting and a visible retention policy; no silent deletion of songs.
- Queue admission, per-user/global concurrency limits, logs/alerts and DB backup.

Plan for roughly 1–2 focused development weeks after Phase 1 for the next usable
editing/clip iteration, then a paid beta only after these gates pass. Provider
onboarding and real-user acceptance are external dependencies, not fixed dates.

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
