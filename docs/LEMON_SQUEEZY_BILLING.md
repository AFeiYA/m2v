# Lemon Squeezy billing — 2026-10-19

## Scope and branch

Updated pricing/expiry policy: 2026-10-19.

Implemented in `feat/lemon-squeezy-billing`, based on the current main UI. The older
`feat/subscriptions-and-topups` branch is a sandbox prototype; do not deploy its
mock checkout or merge it into this implementation. Billing is disabled by default.

The application uses Firebase only to authenticate the existing user. PostgreSQL
(or isolated SQLite in tests) owns checkout intents, subscriptions, immutable credit
history and a replayable webhook inbox. Lemon Squeezy owns payment details, tax
collection for its transactions, checkout, recurring collection, cancellation,
receipts and billing portal. We never collect/store card data, full webhook bodies,
payment-provider access tokens from customers, or signed portal/receipt links.
The merchant API/signing keys belong in backend deployment secrets, never Pages.
Hosted checkout URLs are short-lived and stored in the owner-scoped checkout row.

## Commercial policy implemented

- Single-quantity, fixed-price USD credit packs and monthly credit subscriptions.
- Official commercial catalogue:
  - **One-time Credit Pack**: $4.99 for 200 permanent credits (`topup`). Credits never expire.
  - **Creator Subscription**: $9.99/month for 600 monthly credits (`subscription`).
  - **Pro Subscription**: $24.99/month for 2,500 monthly credits (`subscription`).
  - (Test fixtures also permit the earlier sandbox catalog: $5/mo 1000 credits, $10/mo 2500 credits, $5 500 permanent credits).
- Free account quota policy:
  - New users receive **100 permanent credits** on registration (`NEW_USER_PERMANENT_CREDITS = 100`).
  - After consuming permanent credits, free accounts receive **20 credits every calendar month** (`FREE_MONTHLY_QUOTA = 20`).
- Subscription credits expire at the end of EACH BILLING PERIOD (anniversary,
  not the first of the calendar month). Unused credits do not roll over. Successful
  renewal starts a fresh allocation; failed renewal cannot retain the old one.
- Permanent packs never expire and are kept separate. Spend subscription credits
  with the soonest expiry first, then permanent credits. Existing unclassified
  balances/admin grants remain permanent; no destructive historical backfill.
- Credit lots and per-attempt reservations preserve provenance. Failed jobs restore
  only still-valid monthly credits plus their permanent portion. Holding a job
  past the period end cannot turn expired monthly credits into permanent credits.
- Expiry and financial reversals are separate immutable entries. Refunding an
  expired credit never debits it twice. Refunded credits already consumed by work
  can still produce debt; a negative balance is not erased at the month boundary.
- No unlimited rendering, storage increase, priority queue or UserPlan upgrade is
  promised by a subscription. It purchases the configured monthly credits only.
- Credit amounts and variant IDs are frozen in the checkout intent; modifying the
  catalogue cannot silently reprice an existing customer's recurring grant.
  Create a NEW variant/product when changing an existing subscription's credits.
- Cancelling a subscription stops future renewal through the provider. It does not
  erase permanent credits. Current monthly credits last until their period ends.
  Status, renews_at and ends_at are shown to its owner.
- Subscription order_created NEVER grants credits. Only paid initial/renewal
  subscription INVOICES grant, once per invoice. Recovered duplicates grant nothing
  extra. Proration/update invoices do not purchase a full monthly allocation.
- The first subscription payment has both an Order and an Invoice. A refund on
  either reverses its initial grant once; it never reverses unrelated renewals.
- Partial refunds reverse the ceiling of the corresponding fraction of credits,
  based on the cumulative refunded amount / original total. Full refunds reverse
  all credits. Already spent refunded credits can create a negative balance; future
  purchases repay that debt. Existing reservations, assets and downloads remain.
- There is no customer-facing self-refund endpoint. Issue refunds in the merchant
  dashboard, then verify the webhook/ledger reversal. Publish the refund policy
  and customer-support contact before enabling real sales.
- Free trials, free/100%-discount checkouts, tier/quantity/usage changes, annual plans,
  bundles and currency conversion are outside this version. Disable plan changes
  in the provider portal; use it for cancel/resume, payment details and invoices.

Current product usage pricing remains separate: alignment uses its existing
credit price (1 credit); standard lyric exports and authenticated Motion Design exports
support quoted reservations/refunds. Motion exports support dual-tier execution:
- **Local WebCodecs GPU fast export** (`MOTION_WEBCODECS_CREDITS` = 5 credits): instant client-side MP4 generation.
- **Cloud Chromium headless render** (`MOTION_EXPORT_CREDITS` = 30 credits): server-side fallback and queued render.
- Upfront capability probe (`VideoEncoder.isConfigSupported`) informs deterministic pricing before export, with confirmation dialog before fallback.
Rhythm Studio remains free. Resolution-specific, excerpt-specific and separation
surcharges are not complete; keep `DRAFT_EXPORT_CREDITS`, `CLIP_EXPORT_CREDITS`
and `SEPARATION_CREDITS` at zero. Before changing prices, verify the charge shown to the user matches
all public rendering paths. Existing downloads and unchanged import reuse are free.

## Provider setup

1. Complete merchant approval. Create one regular USD product/variant for each
   credit pack, and one USD monthly standard subscription product/variant. No
   setup fees, metered billing, quantity tiers or free trials. Choose final prices
   and credits in the merchant dashboard and server catalogue together.
2. Use an isolated staging backend + database for Test mode. Set backend secrets:
   BILLING_ENABLED=true, LEMONSQUEEZY_API_KEY, LEMONSQUEEZY_WEBHOOK_SECRET,
   LEMONSQUEEZY_STORE_ID, LEMONSQUEEZY_TEST_MODE=true,
   BILLING_ALLOW_TEST_TRANSACTIONS=true. Never share the production database.
3. LEMONSQUEEZY_ALLOWED_HOSTS is a comma-separated EXACT allowlist. Include your
   real `<store>.lemonsqueezy.com` (or configured custom billing hostname) and
   `app.lemonsqueezy.com` for receipt/invoice links. Wildcards are not supported.
4. BILLING_SITE_URL must be your HTTPS frontend origin (no path/query), e.g.
   https://mv.fovea.si. Checkout returns to /?checkout=<intent>#credits-section.
   Returning alone never grants credits; the UI checks the server's ledger status.
5. Set BILLING_PRODUCTS_JSON with these three fixed offers:

```json
[
  {"id":"monthly_1000","name":"Monthly 1,000","variant_id":"FIRST_NUMERIC_VARIANT_ID","kind":"subscription","credits":1000,"price_cents":500,"currency":"USD"},
  {"id":"monthly_2500","name":"Monthly 2,500","variant_id":"SECOND_NUMERIC_VARIANT_ID","kind":"subscription","credits":2500,"price_cents":1000,"currency":"USD"},
  {"id":"permanent_500","name":"Permanent 500","variant_id":"THIRD_NUMERIC_VARIANT_ID","kind":"topup","credits":500,"price_cents":500,"currency":"USD"}
]
```

Replace all three variant placeholders with digit-only IDs. An empty catalogue or
mismatched provider store/currency/current Price object fails closed. Fixed prices
are read from the current Prices API, not deprecated variant price fields. Displayed
prices exclude applicable tax; the hosted checkout shows the final total.

6. Add the webhook to the BACKEND, not the static Pages domain:
   https://lucazhou-suno2mv-api.hf.space/api/payments/webhook/lemonsqueezy
   Use the same signing secret and environment. Subscribe to:
   order_created, order_refunded, subscription_created, subscription_updated,
   subscription_cancelled, subscription_resumed, subscription_expired,
   subscription_paused, subscription_unpaused, subscription_payment_success,
   subscription_payment_failed, subscription_payment_recovered,
   subscription_payment_refunded.
7. Deploy backend first so init_db creates the additive billing tables, then Pages.
   Existing users/tasks/credit history are not rewritten. PostgreSQL cross-replica
   behavior must be verified on staging; SQLite concurrency tests are not a PG
   load test. Back up and restore-test the database before real collection.
Run `python -m scripts.billing_preflight` on staging to verify provider products
and database access without creating any checkout or charge.

8. After staging acceptance, use LIVE keys, LIVE variants/webhook, TEST_MODE=false,
   ALLOW_TEST_TRANSACTIONS=false, and the production DB. Enable sales only after a
   live purchase/refund acceptance test by the operator. Code/tests do not prove
   merchant approval, payouts, real bank settlement or production callback reachability.

## Reliability and operations

Every recognized callback verifies HMAC SHA-256 over the RAW body in X-Signature,
with a 64 KiB body limit and strict store/test-mode matching. Owner, variant and
one-use checkout-to-order binding are verified. Canonical provider resources are
fetched before applying money effects; stale paid deliveries cannot undo refunds.

A database mutex serializes binding and ledger commits across processes. A durable,
minimal inbox records only event identity, resource identity and a verified checkout
reference, before provider calls. Subscription/invoice reordering returns 503 until
the subscription can be linked. Any failed grant transaction rolls back completely;
the inbox remains pending. Exact delivery replays skip already processed events;
resource IDs prevent financial duplicates even if payloads/event names differ.

Expiry is enforced on balance reads, reservations, grants and reversals under the
user-row lock, so delaying a scheduler cannot spend expired credits. The UI shows
separate monthly/permanent balances and the next expiry, and refreshes at that
boundary. A read-only page refresh is not required for server-side enforcement.
Current provider renews_at is used for the current invoice when valid; old invoices
use their invoice creation month and billing anchor (including short/leap months).
Late/out-of-order invoices cannot reopen an old period or reset a newer allocation.

`python -m scripts.expire_subscription_credits` can sweep up to 1,000 accounts for
physical DB expiry updates even while users are offline. It does not delete money
history, songs, packs or other assets. The replay command also runs this sweep.

Schedule `python -m scripts.replay_billing_events` every five minutes on the billing
backend. It uses current environment secrets, retries up to 100 pending records and
returns nonzero while failures remain. Multiple schedulers are safe. This command
is implemented but no production scheduler is provisioned by this code change.
Alert on nonzero exit/pending backlog. Merchant Dashboard webhook replay is also
available if the ORIGINAL event never reached the server (no inbox record exists).
Do not manually edit balances or mark an event processed to silence an alert.

The authenticated Check recent payments button re-fetches at most 20 known payments;
it cannot discover an initial purchase whose webhook never arrived. Operators must
replay that event in Lemon Squeezy. Pending events and financial history currently
have no automated deletion policy; decide retention/backups before broader launch.

## Acceptance checklist

- Unauthenticated/other-owner checkout status, order history, portal and receipts fail.
- A declined/abandoned checkout grants nothing. A return URL cannot mint credits.
- Monthly expiry, partial spend, held-job failure before/after expiry, concurrent
  expiry reads, late old invoices and refunds after expiry preserve permanent packs.
- Paid pack grants once; double click/delivery, network retry and concurrent callbacks
  do not double charge the application balance. Remote checkout creation errors
  never grant credits. Check merchant orders before retrying uncertain payments.
- First subscription invoice grants once; first order/created/recovered duplicates
  do not. Renewal adds once; failed payment adds nothing; cancellation preserves
  prior credits and shows the correct end date.
- Invoice arriving before subscription, provider downtime, app restart, pending inbox
  replay and canonical-state refresh recover without duplicate ledger entries.
- Partial/full/repeated/out-of-order refunds, including insufficient balance, preserve
  a consistent immutable ledger. A second order cannot steal a used checkout binding.
- Products with changed prices/currency/environment/variant fail before checkout.
- Receipt and portal links are freshly fetched, exact-host validated and not logged.

Official integration references:
[Checkout](https://docs.lemonsqueezy.com/api/checkouts/create-checkout),
[Prices](https://docs.lemonsqueezy.com/api/prices/list-all-prices),
[Webhooks](https://docs.lemonsqueezy.com/guides/developer-guide/webhooks),
[Event lifecycle](https://docs.lemonsqueezy.com/help/webhooks/event-types),
[Customer portal](https://docs.lemonsqueezy.com/guides/developer-guide/customer-portal).
