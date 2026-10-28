# Credit history and reservations

Updated: 2026-10-24. This document describes usage accounting. Current subscription
plans are in [Billing policy](BILLING_POLICY.md); Paddle activation is in
[Go-live guide](PADDLE_GO_LIVE_ZH.md).

`ALIGNMENT_CREDITS` defaults to **20** per new alignment. Reusing a valid,
unchanged import remains free. User-facing video export is exclusively in Motion
Studio; local/cloud exports default to **10** per video. The retired Lyric Editor
export route and `LYRIC_EXPORT_CREDITS` are compatibility code, not a free export offer. Deployed environment
values override defaults. Subscription purchases and usage deductions are separate.
No public endpoint allows arbitrary balance adjustment.

## Accounting

- `users.credits` remains the **available** balance for backward compatibility.
- `credit_reservations` records held/settled/released amounts per owner and
  operation. `credit_entries` records immutable opening/reserve/settle/release/
  administrator-grant events. Both tables are created by normal `init_db`.
- Existing balances are adopted as a starting-balance event on first accounting
  use. Past transactions are not invented or retroactively reconstructed.
- Reserving reduces available credits; completing the operation settles the hold
  without a second deduction. Failure returns the hold. Retrying a failed export
  reserves its original price again; only a successful attempt has a net cost.
- Balance updates, reservation changes and ledger events share one transaction.
  Per-user row locks and deterministic event keys protect concurrent requests and
  duplicate completion/failure callbacks. Account history locks the balance while
  reading history/reservations to return a consistent snapshot.
- Successful alignment is settled with the Task completion transaction, after
  alignment JSON and ASS uploads are verified. Render settlement is in the same
  transaction as publication of its downloadable VideoExport.
- Export interruption detection returns its held credits in the same transaction
  as marking it interrupted. Deleting an unfinished project releases held credits.
  Completed project deletion does not refund successful work or erase history.
- Legacy task failures retain the existing one-time refund behavior. New imports
  use the alignment execution leases described below. Legacy tasks without leases
  are not failed just because they are old.
- **Free experience**: new accounts receive **60 permanent credits** once
  (`NEW_USER_PERMANENT_CREDITS=60`). At current default rates this covers two
  alignments (2×20) and two Motion exports (2×10), not two videos per song.
- **No recurring free allowance**: `FREE_MONTHLY_QUOTA=0` by default. The legacy
  optional monthly quota implementation remains available for explicit operator
  configuration, but is not part of the current product offer.
- Deployment must update both environment variables; changing a code default does
  not override an existing server setting or rewrite an existing account balance.

## Client and API

`GET /api/credits?page=1&page_size=20` is authenticated and owner scoped. It returns
available/reserved balances, wallet breakdown (expiring monthly vs permanent credits),
`monthly_quota` eligibility status, paginated activity and current prices. The dashboard
shows the ledger and export dialog shows the price before submission.

### Motion Studio Export Pricing & Song Buyout

Motion Studio supports local WebCodecs encoding and cloud Chromium rendering.
Video exports operate on a **single-song buyout model**:
- First export for a song charges 10 credits (`MOTION_EXPORT_CREDITS` / `MOTION_WEBCODECS_CREDITS`), unlocking the song for video export.
- Once unlocked, all subsequent exports of any visual mode (Kinetic Posters, Apple Music Scroll, Dual-line Karaoke), any aspect ratio (16:9, 9:16), custom clips, or re-renders cost **0 credits** (unlimited free exports for that song).
- Browser capability detection does not prove that a full render will succeed; if local encoding fails, the export automatically falls back to cloud rendering without extra charge.
- Browser-rendered files must upload successfully and become a durable VideoExport before settlement and appearance in My Exports. A failed save can retry the same request/file without rendering again; refresh currently loses an unpublished file held only in page memory. See [release TODO](TODO.md) for real-network acceptance.

Legacy API maintenance only (not the current product export workflow):

1. Deploy the updated frontend, backend and worker code together and verify the displayed price. Do not leave old workers modifying balances outside the ledger.
2. Paid render requests require a UUID `request_id` and matching `accepted_cost`.
   Old clients without price acknowledgement are rejected rather than charged.
3. Paid retries require `accepted_cost` matching the original job's cost, displayed
   by `/api/editor/render-jobs`. A deployment must not reprice an existing retry.
4. Combined import-and-render requests are blocked. Import alignment only, then
   use the supported Motion Studio export workflow. This prevents the old
   pipeline-video route from bypassing export accounting. Local CLI video creation
   is not a cloud credit service and is unaffected.
5. Native downloads and access-link refreshes never deduct credits.

The editor retains the request UUID after an ambiguous network error. Unchanged
saved alignment and export options reuse it; changed input gets a new UUID. On
successful/failed terminal status it clears that pending request. Stored request
metadata contains a revision hash and output options, not account tokens or lyrics.

## Administrator test grants

Use an authorized backend environment with DATABASE_URL set, from the repository
root: `python -m scripts.grant_credits --user-id <id> --amount 10 --reference <unique-id>`.
Repeat the same reference to safely retry a grant; changing its amount is rejected.
This is a trusted CLI, not a public API. Do not directly edit users.credits after
ledger adoption: that would bypass history. No real user balances are changed by
unit tests or by deploying this feature.

Payment-order/webhook idempotency and three monthly subscriptions are implemented
in the current payment adapters, with Paddle as the selected launch provider.
Subscription expiry uses `credit_lots` and per-attempt `credit_allocations`.
Permanent and legacy credits do not expire. See [Billing policy](BILLING_POLICY.md)
for current plans and [Paddle go-live](PADDLE_GO_LIVE_ZH.md) for activation gates.

## Alignment preparation and interrupted workers

- Task, unique import claim, execution lease and credit hold are committed together
  **before** Suno audio downloads or storage writes. An identical concurrent import
  reuses that task without needing another credit. A different import must reserve
  its own credit before performing expensive preparation.
- Preparation exceptions (including request cancellation) mark the durable task
  failed and release its hold. Cleanup is best effort and limited to the request's
  own assets; reused audio is never deleted. Preparing tasks cannot lend their
  not-yet-finalized audio to a different lyric version.
- `alignment_executions` is a new table created by `init_db`; existing Task columns
  need no migration. Preparing/running leases last 120 seconds, renewed every
  10 seconds by an independent thread, including during blocking model inference.
  Queue handoff allows 30 minutes before a worker starts. Queue duration is a
  capacity limit, not an inference timeout.
- A worker atomically claims the queued execution token once. Duplicate deliveries,
  legacy invocations of a managed task, expired executions and deleted tasks cannot
  publish successful Task results or settle credits. Live progress is not required
  for liveness. Completed/failed states never become active again.
- Owner task/credit queries, Suno/upload requests and an open progress WebSocket
  reconcile expired managed executions. Each recovery uses its own short transaction
  for status plus refund, without holding one task's balance while locking another
  task. The request's cached ORM objects are then refreshed. No user activity means
  recovery waits until the next query; there is no always-running global scheduler.
- Recovery reports interruption and returns held credits once. It does not promise
  continuation from a half-finished GPU stage or silently rerun the song. The user
  can import again. A process kill during upload can still leave orphaned objects;
  retention cleanup is separate from credit recovery.
- Deploy backend **and** Celery workers together. Old queued tasks without managed
  leases remain compatible. An old worker must not consume new leased tasks during
  rollout, since it lacks the token guard and independent heartbeat.


## Motion Design exports

`MOTION_EXPORT_CREDITS` is the fixed cost per authenticated Motion Design video.
The default stays zero; setting a positive integer enables credit charging after
matching frontend/backend deployment. There are no additional resolution or clip
surcharges. Rhythm Studio and local-only renders remain free.

The matrix displays per-video cost and the selected total. Every cell has an
independent UUID; ambiguous submission retries retain it. A changed price must
be reviewed again. Paid API requests lacking a UUID or matching `accepted_cost`
are rejected before starting work. `motion_export_requests` is an additive table
created at startup. It stores owner, source task, canonical request fingerprint,
frozen cost, state and a 120-second lease, without storing account credentials.

Admission atomically reserves the render slot and credits. Private video upload
and size verification precede publication; VideoExport and credit settlement
commit together. Failures/cancellation release once using the existing monthly
expiry rules. Successful cancellation cannot revoke an already published video
or refund delivered work. Worker leases refresh every 10 seconds; stale requests
are fenced and refunded when credit history, Motion status or another Motion
admission is read. This is lazy recovery, not a newly provisioned scheduler.

Replaying an accepted UUID returns the same job, including across container
restarts, without rendering or charging again. A failed/cancelled terminal job
needs a new UUID for a new attempt. New jobs use current prices; old jobs keep
their accepted price. Downloads and changing themes locally remain free.
