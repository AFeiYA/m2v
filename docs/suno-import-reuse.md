# Suno import identity and media reuse

- Resolve both `/s/...` and `/song/...` to the fetched song ID. New task URLs use
  `https://suno.com/song/{id}`, without tracking parameters. IDs are case-insensitive.
- Within one account, identical lyrics and alignment options (`language`, `skip_separation`) reuse a valid task.
  Different lyrics/alignment options and explicit realignment create separate task snapshots.
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

## Video rendering is separate from alignment

`ass_only` and `beat_effects` are output choices, not alignment identity. Switching
these choices does not create another alignment task or charge alignment credits.
Suno imports default to alignment/subtitles only (`ass_only=true`).

For an already completed import, an explicit `ass_only=false` request reuses the
saved timeline (including manual timing edits) and original audio, and starts a
render-only editor video job. The response retains the existing `task_id` and
adds `video_job_id`. The dashboard tracks this job separately and refreshes My
Exports when it completes. No separation/alignment worker is dispatched. Existing
pending imports remain the same task; the response instructs users to export from
Lyric Editor after alignment is ready. First imports and explicit realignments
still require the normal audio/alignment pipeline.

Render-only MP4 objects use `results/{task_id}/exports/{video_job_id}.mp4`. Their
VideoExport records point to that exact object key. Download through
`/api/exports/{video_job_id}/access`, not the old task's `output_mp4_key`: it returns
a fresh private R2 signed URL (or a scoped local ticket). Render failure leaves
the original audio and saved timeline unchanged. Render theme/effects are chosen
in Lyric Editor; the import beat checkbox does not rewrite an existing timeline.
