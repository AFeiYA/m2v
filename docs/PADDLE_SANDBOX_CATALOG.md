# Verified Paddle sandbox catalog

Verified through the authenticated Paddle sandbox dashboard on 2026-10-23.
This records sandbox resources only; it does not enable billing or change live resources.

| Application package | Product ID | Price ID | Base price | Grant |
| --- | --- | --- | --- | --- |
| `topup_200` | `pro_01m5kr7rrkvk3dx1g5c8z0ty3n` | `pri_01m5kraresbevj8yx4ycr5d90d` | USD 4.99 one-time | 200 permanent credits |
| `pro_monthly` | `pro_01m5krbdz9xs8mkw9n1m55h897` | `pri_01m5kse2g2ha98mqakx7168gz8` | USD 9.99/month | 600 credits per billing period |
| `studio_monthly` | `pro_01m5m7kaknpsh2psjxdp2xj8b1` | `pri_01m5m7kvw27py216xh53fwksfs` | USD 24.99/month | 2,500 credits per billing period |

All products use the SaaS tax category. Prices exclude tax, have no trial,
and permit quantity 1 only. Monthly credits expire at the billing-period end
without rollover. The application, rather than the Paddle product itself,
must implement credit grants and expiration.

## Currency policy

The user chose USD base prices with automatic currency conversion instead of
country-specific purchasing-power prices. The temporary GB/IE/AU overrides on
the top-up price were removed; both monthly prices also have no overrides.
The sandbox Currencies page confirms **33 active conversions**, including
GBP, EUR and AUD. Balance currency remains USD.

To adjust this later: My account > Settings > Currencies > Active conversions.
Automatic exchange conversion does not implement purchasing-power discounts.

## Integration evidence and remaining acceptance

Catalog setup is complete, but a browser login does not supply the backend
with sandbox API credentials or a webhook signing secret. Configure those
privately using the sandbox setup guide before end-to-end testing.

The current application checkout explicitly requests USD and its fulfillment
validations expect USD. Enabling conversions in the Paddle dashboard alone
does not prove that application-initiated checkouts accept localized payments.
Before offering localized checkout, implement and test server-validated currency
and amount snapshots for payments, subscriptions, renewals and refunds. Do not
simply remove currency checks. No real payment or sandbox card transaction was
performed as part of catalog setup.


On 2026-10-24, real sandbox Checkout completed a USD 4.99 credit pack and a USD 9.99 monthly subscription first payment. The isolated backend recorded 200 permanent credits and 600 expiring monthly credits respectively. Actual payment webhooks were processed; a repeated known transaction did not grant twice. Checkout used a temporary test page, not the complete production workbench. Real renewal, cancellation, refund approval and current workbench browser acceptance remain distinct checks. Temporary tunnel and test servers were stopped. See [release guide](PADDLE_GO_LIVE_ZH.md).
