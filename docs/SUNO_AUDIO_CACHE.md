# Suno audio-only download identity

Updated: 2026-10-27.

`/api/suno/download_mp3` resolves the submitted URL once and uses the resulting
song UUID as identity. A short link and a full `/song/UUID` link share a cache
when they resolve to the same UUID. Titles and raw URL strings are not identities.

Audio-only source files live under `input/suno/<UUID>/`. The browser still receives
the song title as its suggested MP3 filename. Different UUIDs cannot collide even
when their titles and lyrics are identical.

The shared downloader checks a separate `<audio filename>.source.json` provenance
record containing the UUID, filename, byte size and SHA-256 digest before reusing
audio. It also checks that the file is decodable. Mutable `_suno.json` metadata is
never accepted as proof of which song an older audio file belongs to.

For the same UUID, changed lyrics or metadata update their files without another
audio download. Unchanged text files are left untouched. Renaming a song also
keeps its verified audio. Audio-only requests never run separation or alignment.

Downloads and conversions write a temporary file first. Only validated complete
audio is published and given a provenance record. Interrupted or failed transfers
cannot become reusable cached audio.

Legacy title-only audio is not automatically adopted, even if its metadata now
contains the requested UUID: the old downloader may have overwritten that metadata
before returning the wrong audio. Audio-only downloads create a new UUID-scoped
copy and preserve legacy directories. Local fallback accepts only verified
provenance or a filename containing the complete requested UUID; title-only exact
and fuzzy matches no longer qualify. Users can explicitly upload unidentified
audio instead. Cloud imports continue to disable local fallback entirely.

Offline regressions cover same-title distinct UUIDs, short/full URL aliases,
lyric updates, renames, overwritten legacy metadata, damaged provenance, changed
audio, interrupted downloads and conversion failures.
