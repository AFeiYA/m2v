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

## Missing stored alignment

A database key is a reference, not proof that the object still exists in the active
bucket. Editor song discovery omits missing alignment objects, and direct reads
return 404 with a reimport instruction. S3/R2 object-not-found errors are normalized
to the same missing-file exception as local storage; permission and service errors
remain retryable failures (503 at the editor API), rather than being treated as
missing data. Logs include the task ID and object key for investigation. These
reads do not delete or rewrite task records or fabricate replacement timestamps.
Reimport checks the stored result exists before reusing a completed task and can
reuse the original audio if it is still present.
