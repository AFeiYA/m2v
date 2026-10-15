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
