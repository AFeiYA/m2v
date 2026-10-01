# pdoom source provenance

Upstream: https://github.com/mexicat/pdoom-video
Commit: bdbad537a7b7af3213475651774030c47568c181

`post.ts` is adapted from `app/src/engine/post.ts` under the accompanying MIT
license. Changes: instance dimensions for portrait/landscape, resource disposal,
and a defined-edge vignette expression. Its seven-level bloom/halation/grain
chain is retained. `gl.ts` contains the minimal fullscreen pass and math helpers
adapted from upstream gl.ts and glsl/common.ts. No original song, lyric text,
font files or song-specific scenes are included.

m2v's generic Chinese text scene, data adapter, UI, and Node exporter are new.
The exporter follows the upstream raw RGBA → WebSocket → FFmpeg approach;
it does not port the song-specific engine or adaptive motion-blur sampler.
