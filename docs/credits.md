# Credit history and reservations

The first billing phase adds accounting, not a payment provider or subscription.
The existing alignment price remains 1 credit per new task; reuse of a valid,
unchanged import remains free. `LYRIC_EXPORT_CREDITS` defaults to **0** (free).
No payment or public balance-adjustment endpoint is exposed.

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
- Legacy task failures retain the existing one-time refund behavior. Alignment
  failure still relies on the Task worker reporting failure; a killed alignment
  worker without a failure report can remain reserved. This phase does not add an
  alignment-worker lease/watchdog or automatic monthly credit grants. Despite its
  existing name, FREE_MONTHLY_QUOTA is currently used as the initial allowance.

## Client and API

`GET /api/credits?page=1&page_size=20` is authenticated and owner scoped. It returns
available/reserved balances, paginated activity and current prices. The dashboard
shows the ledger and export dialog shows the price before submission.

If an administrator later chooses a nonzero LYRIC_EXPORT_CREDITS:

1. Deploy the updated frontend, backend and worker code together and verify the displayed price. Do not leave old workers modifying balances outside the ledger.
2. Paid render requests require a UUID `request_id` and matching `accepted_cost`.
   Old clients without price acknowledgement are rejected rather than charged.
3. Paid retries require `accepted_cost` matching the original job's cost, displayed
   by `/api/editor/render-jobs`. A deployment must not reprice an existing retry.
4. Combined import-and-render requests are blocked. Import alignment only, then
   export through Lyric Editor with a reviewed price. This prevents the old
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

Before paid public launch, add payment-order/webhook idempotency and aligner worker
restart reconciliation. Currency pricing, expiry policies and subscriptions are
not implemented by this credit ledger.
