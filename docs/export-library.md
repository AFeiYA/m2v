# My Exports

The authenticated dashboard shows a paginated export library. Closing the editor,
refreshing, or restarting the compute container does not remove its records.

## Persistence

- `video_exports` stores owner, song task, object key, type, creation time and small
  rendering metadata in the existing SQL database. `init_db` creates the new table.
- Video bytes remain in the configured private storage backend (R2/S3 or local).
- Lyric Editor and authenticated Motion/Rhythm exports register on completion.
- "Find earlier exports" explicitly scans the owner's latest 100 projects for
  older files, including the original pipeline MP4. Recovered metadata may be
  incomplete and the discovery time is shown when original timestamps are unknown.
- Deletion keeps a database tombstone so recovery cannot resurrect a deleted item.
  It removes the video, not its source song/alignment. Deleting the entire song
  removes its associated export records/files too. No automatic expiry is added.

## Delivery

- `GET /api/exports` lists metadata; it never loads MP4 data.
- `GET /api/exports/{id}/access?preview=true|false` checks ownership and returns a
  15-minute media URL. For S3/R2 this is a private presigned GET, ignoring any
  legacy public domain configuration. Downloads use attachment disposition.
- Local storage uses a signed, single-export media ticket. It is not an account
  token and is rechecked against the live export row on each media request.
- `DELETE /api/exports/{id}` deletes the artifact.
- `POST /api/exports/discover` finds earlier artifacts.

The Lyric Editor shows its result immediately and fetches an access URL only on
Preview or Download. It no longer downloads the entire MP4 into a Blob before
showing completion. Native video/attachment requests do not put the account token
in a URL. New access URLs are requested each time a user retries.

## Durable lyric render requests

`export_jobs` is the source of truth for cloud **Lyric Editor** renders, including
video requests made while reusing a Suno import. The new table is created by the
normal `init_db` startup path. It stores the owner, song, validated options, input
object references, status/progress, attempt count and a worker lease. The local
TaskStore remains only for audio-analysis compatibility, not new lyric renders.
Motion/Rhythm retain their existing renderer status handling; their completed
videos still use the shared `video_exports` library.

- `GET /api/editor/render-jobs` lists the owner's latest 50 active/failed/interrupted
  jobs (active first), without private object keys or render settings.
- `GET /api/editor/jobs/{id}` reads durable status, even after local journal loss.
- `POST /api/editor/jobs/{id}/retry` retries only failed/interrupted lyric renders.
  It uses the saved options and the currently saved timeline at the same input
  object key, never redownloads Suno audio or invokes separation/alignment inference.
- `DELETE /api/editor/jobs/{id}` dismisses a failed/interrupted request; it does not
  delete the song, source audio or timeline. Active jobs cannot be dismissed.
- Queued/running/uploading attempts refresh a lease every 10 seconds. If a worker
  stops without shutting down cleanly, status/list requests mark the expired job
  interrupted after 120 seconds. A still-live worker in another serving process
  is not marked interrupted just because a new process starts. Reading status
  never restarts a render automatically. Retry clicks and request IDs are deduped
  in the database, including across processes.
- Every attempt writes a separate object:
  `results/{song_task_id}/exports/{job_id}/{attempt_token}.mp4`.
  Old attempts cannot publish after losing ownership, overwrite a retry's MP4 or
  delete its object. The private download URL always comes from the completed
  VideoExport record, never a guessed file path.
- Success requires a nonempty render, a completed upload and remote object/size
  verification. The VideoExport row and completed job state commit together.
  Failed publication does not advertise a completed video; unpublished files are
  cleaned up when possible. An abrupt process kill can leave an unindexed object;
  no automatic bucket cleanup or automatic rerender is introduced in this phase.
- S3/R2 permission/network failures now propagate as storage failures, instead of
  masquerading as absent files and triggering unnecessary processing. Media access
  returns a retryable 503 for storage failures, distinct from a missing-file 404.

The dashboard restores progress on login and periodically refreshes while jobs
are active. Failed/interrupted jobs offer Retry rendering and Dismiss. Completed
jobs move into My Exports; Preview/Download still fetch media only on demand.
Rendering still runs on the serving process with a two-slot limiter per event
loop. The database makes state durable; it is not an external job queue and does
not resume a killed FFmpeg process mid-frame. No new credit charges are added.
Old unfinished TaskStore-only exports cannot be reconstructed into new jobs when
their settings have already been lost; submit a new export from the saved song.
