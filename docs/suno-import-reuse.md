# Suno import identity and media reuse

- Resolve both `/s/...` and `/song/...` to the fetched song ID. New task URLs use
  `https://suno.com/song/{id}`, without tracking parameters. IDs are case-insensitive.
- Within one account, identical lyrics and processing options reuse a valid task.
  Different lyrics/settings and explicit realignment create separate task snapshots.
  Old results are preserved; failures do not overwrite them.
- Those versions reference the same available original audio object. Only missing
  originals are downloaded again. Media is never borrowed from another account or
  matched by title.
- Workers can restore vocals/instrumental from a previous completed version before
  running the pipeline. They never restore its alignment JSON. Missing stems fall
  back to separation. Stem outputs still belong to their individual result tasks.
- Deleting a task removes its lyrics/results. Original audio and source artwork
  remain while another task references that audio; the final deletion removes them.
- This does not merge existing task rows, retroactively deduplicate stored files,
  or introduce a single song/project table. Task history remains versioned.
