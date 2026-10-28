# Motion design and rendering

Updated: 2026-10-29. This document describes the staging authoring model.

## Authoring document

`source_motion_design.json` is the single saved visual-design document for a
cloud song. Local projects use `<song>_motion_design.json`. The alignment JSON
continues to own lyrics, word timestamps, sections, and audio analysis. Credits,
cover artwork and song identity remain shared song assets.

The document has `version: motion-design-v1`, `active_mode`, a shared `theme`,
export `height`, and `modes` keyed by `kinetic`, `apple`, and `tv`.

Each mode remembers its own aspect, optional theme override and presentation
settings. Kinetic owns its poster plan (semantic nodes, emphasis, entrances,
highlights and locked cues). Apple owns its lyric size and focus position. TV
owns its lyric size and pre-reading interval. Streaming modes do not contain
synthetic poster plans and cannot rewrite the kinetic namespace.

The Theme scope control explicitly chooses between this mode only and all
modes. All modes updates the shared theme and clears mode theme overrides;
applying a palette to poster content preserves its nodes, timings and locks.
Changing aspect never changes the selected mode.

## Editing and saving

Selecting a mode only changes `active_mode` and restores that mode's controls.
Regenerating posters is a separate, confirmed action that replaces unlocked
poster designs. Shared lyrics and source identity are never rewritten by a mode
switch. Switching songs restores that song's own document rather than the last
value displayed in the selector.

`PUT /api/motion/design` (or the authenticated `/api/cloud-motion/design`) validates
and writes the complete document. Poster design and mode preferences therefore
cannot be partially saved as separate requests. Song identity remains a separate
shared asset; if either save fails, the relevant draft remains unsaved. Edits made
while saving are not cleared by an older response. Director/AI endpoints operate
only on `modes.kinetic.plan` and preserve the other namespaces.

This is a new authoring format. Old `_motion_plan.json` and `_motion_settings.json`
files are not imported, deleted, or overwritten. Testing should use new design
documents; deployments must update frontend and backend together.

## Compiled render plan

`frontend/motion/src/render-plan.ts` is the shared layout compiler for Remotion
preview, cloud rendering, and WebCodecs encoding. It resolves the requested mode,
theme, font metrics and target dimensions into measured layouts and animation
intervals. These layouts are derived, not saved back into the authoring document.
The poster compiler receives a derived `motion_plan` input, not a second saved
copy of the design. Source lyrics and timestamps remain unchanged.

Every export matrix entry names its mode, aspect and clip. Portrait TV remains
TV; landscape Apple remains Apple. Exports use a snapshot of the selected song
and design so later editor changes do not affect an in-progress local batch.

## Adding a mode

1. Add its authoring schema and defaults in `src/motion_design.py` and
   `frontend/motion/src/motion-design.ts`.
2. Register its metadata and compiler instead of adding mutations to the mode
   selector. Extend the typed mode identifiers on the API/export boundary.
3. Add the mode's settings panel and renderer. Implement both rendering surfaces
   when the new mode supports both Remotion and local Canvas encoding.
4. Verify mode-switch round trips, save/reload, both aspect ratios, theme isolation,
   source immutability and identical compiled layouts across export surfaces.

Palette/font combinations within an existing mode are presets, not new modes.
This change does not alter pricing or credit accounting.
