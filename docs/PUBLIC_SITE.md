# Public site and authenticated workspace

Implemented 2026-10-22.

## Routes

- `/`: public English marketing page, no Firebase SDK or private API calls.
- `/pricing`: three monthly subscription plans, renewal/expiry terms, FAQs.
- `/app`: existing authenticated workspace, formerly served at `/`.
- `/contact`, `/privacy`, `/terms`, `/refunds`: public support and policy pages.

Cloudflare Pages serves the matching root HTML files directly at extensionless
URLs. No HTML rewrites or catch-all SPA rules were added. Both Python entry points
have explicit routes; the local editor serves the shared marketing CSS/JS as well.
Old root `#tasks-section`, `#exports-section`, editor hashes, `?redirect=` and
`?checkout=` links preserve their query/hash and move once to `/app`. Ordinary
homepage links such as `#how-it-works` remain public.

The workspace HTML was moved to `frontend/app.html`, preserving its existing
scripts, auth and iframe lifecycle. Checkout now returns to
`/app?checkout=<id>#credits-section`. Never grant credits from a return URL.
A public plan CTA carries `?plan=<catalogue-id>#credits-section`; the billing UI
acknowledges the selection after auth, but does not automatically create checkout
or charge. A deliberate in-app purchase click remains required.

## Updating public content

Run `python scripts/build_marketing.py` after editing its copy or updating the
checked-in catalogue. It generates the public HTML only, never workspace HTML.
The generator reads `.env.example`'s public product template, not local `.env`,
merchant keys, user data or deployed settings. Tests compare advertised packages
to that template. Production billing remains authoritative; when pricing changes,
update the server allowlist, merchant variant, template and public site together.

Public previews lazy-load `marketing-preview.js`, using the same `RemotionPreview`
and `LyricVideo` as the studio/export path. `marketing-demo.ts` supplies original
sample lyrics with explicitly synthetic word timings and no cover, audio or beat
claims. Portrait scroll is 720×1280, landscape dual-line is 1280×720, and the poster
sample uses the actual three-stack preset. Fonts, palettes, clipping and entrance
logic come from the production components, not a separate CSS imitation. Playback
requires a click; offscreen/hidden previews pause. The public renderer imports no
authentication, service API, user assets, billing or export functions.

Both Motion build scripts include this browser-only bundle. Pages staging requires
it, and the local editor asset route explicitly permits it. No GPU job, alignment,
paid render or private R2 media is needed to view the samples.

## Before merchant submission

- Support email confirmed by the operator: `support@fovea.si`. Contact page and
  footer use this address for private account, billing, refund and privacy help.
  GitHub remains a secondary channel for public technical issues. Confirm incoming
  messages and replies work for this mailbox. Update the Paddle account contact
  separately in sandbox and production; the website does not synchronize it.
  Confirm the required operator/business identity before submission.
- Review the policy copy against actual operations and applicable requirements;
  the pages are starting copy, not a certification of legal compliance.
- Confirm store approval, live variants, API/signing keys, Webhook delivery and
  successful transaction acceptance using `PADDLE_GO_LIVE_ZH.md`.
- Public plan cards do not enable billing if `BILLING_ENABLED` is false. The
  existing workspace explains unavailable checkout rather than promising a sale.
- Previews show the actual renderer, but are not evidence of AI alignment accuracy.
  Add authorised song exports separately when an audio demonstration is available.

## Verification

- Frontend tests: public navigation compatibility, internal links, catalogue
  consistency, explicit purchase intent (no automatic checkout).
- Pages staging tests: public pages and workspace are materialized; unsafe HTML
  rewrites remain rejected.
- HF entrypoint test: public routes and the workspace are reachable through the
  actual Gradio-mounted application.
- Billing tests retain owner checks, signed Webhooks and transaction semantics.
- Desktop and 390px mobile browser checks: home/pricing, layout selector and no
  document-level horizontal overflow.
