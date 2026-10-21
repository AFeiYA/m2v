# Workspace navigation and editor lifecycle

The four views remain Library → Lyric Editor → Motion Design → My Exports.
The two editors currently use same-origin iframes, kept mounted across ordinary
view changes. The workspace owns navigation; iframe editors own their drafts.

## Ownership

- `dashboard.js`: select a task and request a workspace view. Never assign iframe
  `src` or send an implicit load command.
- `workspace.js`: view visibility, browser history/hash, shared navigation guards.
- `studio-adapters.js`: the only iframe loader, pause/destroy, request identity,
  readiness timeout, retry and invalidation after a successful lyric save.
- `local/studio-bridge.js`: child readiness, loaded/failed, dirty/saving and save
  receipts. Both editors report real operations, not inferred DOM button text.
- `workspace-store.js`: separate draft state for each editor and saved lyric version.

A normal return to the same song does not navigate the iframe or send LOAD_SONG.
The existing audio URL, theme, draft and playback cursor therefore remain mounted.
Changing songs with a dirty editor is blocked with a review message. Motion cannot
open against unsaved lyric edits. Failed saves never mark Motion stale; successful
saves invalidate it once, and the next activation reloads current saved data. A
stale Motion draft blocks refresh instead of being silently overwritten.

## Event contract

Each iframe navigation carries `_workspace`, an opaque per-navigation request ID.
Messages include `studio`, `requestId`, `songId`, `dirty`, `saving`. Loaded events
also contain title; save receipts may contain a server version. Parent acceptance
requires exact origin, expected iframe window and current request ID. An old
iframe's late reply cannot clear a newer loading/error/draft state.

- `M2V_STUDIO_READY`: child bridge initialized, not evidence that a song loaded.
- `M2V_STUDIO_LOADED`: actual project/alignment loaded. Audio may still be buffering.
- `M2V_STUDIO_STATE`: draft/saving state changed; unchanged state is not repeated.
- `M2V_STUDIO_SAVED`: successful save, including whether newer edits remain dirty.
- `M2V_STUDIO_ERROR`: actionable load/preview failure.

A 30-second missing acknowledgement or iframe load error shows a retry action.
HTTP 200 alone is never treated as editor readiness. Retry uses a fresh identity;
dirty drafts block reload. An embedded editor inherits the workspace's explicit
API address and existing auth helper. Presence of a cached login alone does not
select cloud mode for a standalone local editor. Navigation does not start login
popups. Application ownership/authorization stays enforced by the backend.

## Preview regression

The Apple/TV layout addition placed a `useMemo` after the initial layout-not-ready
return in `LyricVideo`. On layout completion the React hook count changed, causing
React #310 independently of iframe routing. Features are now calculated without
that conditional hook. The preview fallback displays its actual error and reports
it to the parent. Tests cover hook sequence for kinetic, Apple and TV modes.

## Validation

Node tests cover repeat activation, wrong origins/windows/request IDs, timeout and
retry, save invalidation, draft guards, same-hash navigation and save-in-flight
snapshots. A synthetic browser exercise verifies Library/editor/Motion/Exports
switching: returning to lyrics adds no alignment request; one lyric save causes
one subsequent Motion project reload. No personal song/account fixtures are used.
