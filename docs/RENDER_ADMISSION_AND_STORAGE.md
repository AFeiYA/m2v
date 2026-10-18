# Render admission, storage limits and backups

## Deployment and branch separation

Main contains the editing review tools, subtitle fixes, resource admission and
storage controls. Payment orders, sandbox payment endpoints and payment-provider
configuration remain on `feat/subscriptions-and-topups`. Main must not mount
`/api/payments/*`. Existing import credit accounting is unchanged; lyric video
export remains free by default. No subscription or checkout is enabled here.

Deploy the backend first so `init_db` creates `render_admission_mutex` and
`motion_render_leases`. Allow in-progress Motion renders from older versions to
finish before restarting: older processes do not participate in the shared lease
protocol. Every replica must use the same PostgreSQL database for shared capacity.

## Atomic admission

A singleton database row serializes capacity checks. The row remains locked until
an ExportJob insert/retry or Motion lease reservation commits. This is not an
in-process asyncio lock: independent event loops and database connections observe
the same reservation. Failed admissions roll back without occupying a slot.

Limits default to two active renders per user and four globally. Lyric jobs and
Motion leases share those limits. Motion renews a 120-second lease every ten
seconds and releases it when rendering/publication succeeds, fails, or cancels.
Loss of the lease cancels the old process; an expired render cannot publish a
completed library entry. Expired leases stop counting towards capacity. Existing
lyric jobs retain their heartbeat and explicit retry lifecycle; expired attempts
cannot renew ownership or publish results.

Independent-loop SQLite concurrency, rollback, expiry, ownership and failure
cleanup are covered by tests. This is not a PostgreSQL load benchmark. Production
rollout should additionally verify multiple replicas against the deployment DB.

## Storage estimates

`GET /api/storage/accounting` and import admission use the same calculation:
active + Trash source audio keys (deduplicated), metadata per version, and visible
export sizes. Trash retains physical source files and therefore still counts.
Unchanged valid Suno imports are reused before the new-import quota check.

`usage.estimated` is true. Audio is currently estimated at 5 MiB per distinct
source and metadata at 200 KiB per version. Separated stems, custom covers and
orphaned files are not an exact inventory. This is a soft admission policy, not a
physical storage meter or transactional byte reservation. An import can cross the
threshold; concurrent in-flight imports can also exceed it. Existing assets are
never automatically deleted by these checks. Do not advertise exact storage
allowances before object-size accounting and in-flight reservations are added.

## Admin backups

`M2V_ADMIN_USERS` accepts authenticated user IDs, not email addresses. If empty,
all callers are denied. The endpoint runs blocking backup work outside the event
loop. SQLite uses its online backup API. PostgreSQL requires `pg_dump`, creates a
custom archive and fails if the utility is unavailable or the command fails.
Passwords are passed via the child environment, not command-line arguments.

Backups and manifests are local files in `backups/`, excluded from Git. They are
not automatically scheduled or copied to durable off-host storage. Archive listing
and checksums do not replace a restore drill. For container deployments, arrange
provider snapshots or durable backup storage before treating this as recovery.
