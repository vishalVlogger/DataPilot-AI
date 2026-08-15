# DataPilot commercial model

DataPilot 0.9 centralizes commercial behavior in `app.services.commercial`. The catalog is the only plan source of truth; `PLAN_CATALOG_JSON` may override public names, descriptions, limits, features, eligibility, ordering, and active state without changing entitlement code. Prices are separate configuration and never imply that money was received.

## Default plans

| Entitlement | Free | Pro | Business |
|---|---:|---:|---:|
| Datasets | 5 | 50 | 500 |
| Members | 3 | 10 | 50 |
| Upload | 25 MB | 100 MB | 500 MB |
| Rows per dataset | 100,000 | 1,000,000 | 5,000,000 |
| Columns | 500 | 500 | 500 |
| Storage | 100 MB | 5 GB | 100 GB |
| Analyses / calendar month | 50 | 2,000 | 20,000 |
| External-AI calls / month | 0 | 2,000 | 20,000 |
| Reports / month | 5 | 200 | 2,000 |
| Exports / month | 20 | 500 | 5,000 |

Free retains PDF reports, saved analyses, workspace export, advanced cleaning, and collaboration for beta continuity. Pro adds external AI and larger capacity. Business adds priority-job entitlement and larger team capacity. Priority is metadata only; no complex scheduler is claimed.

## Effective access and trials

Effective plan resolution is: unexpired active subscription assignment, then active workspace Pro trial, then the workspace base plan. Trials are opt-in, require the owner, default to 14 days, require no payment details, and may be used once per workspace. Expiration is evaluated at access time and falls back to the base plan. It never deletes datasets, versions, reports, members, or saved analyses. Existing over-limit content remains readable; only new creation is restricted.

Usage periods are UTC calendar months. Static resources (datasets, members, storage) come from current metadata. Successful analyses, external-AI calls, reports, and exports use usage events. Stable meter keys make worker retries and request replay idempotent. Failed operations are not metered. Warning levels are configurable and default to 75%, 90%, and 100%.

## Billing domain

`subscriptions` is provider neutral: workspace, plan, status, provider, nullable provider IDs, current period, cancellation, and trial end. Statuses support `none`, `trialing`, `active`, `past_due`, `canceled`, and `expired`. `BillingProvider` has `NoopBillingProvider` and audited `ManualBillingProvider` implementations. A unique workspace subscription makes repeated assignments updates rather than duplicates.

`upgrade_requests` stores the requesting user/workspace, requested plan, optional message, status, and timestamps. Manual approval assigns access only; it is not a transaction. No transaction rows, revenue, MRR, ARR, profit, invoices, taxes, coupons, or refunds are fabricated. Revenue and profit remain explicitly unavailable until a real provider and cost accounting supply authoritative data.

Future Stripe or Razorpay integrations should implement `BillingProvider`, map provider-neutral statuses, and update the unique workspace subscription idempotently from verified webhooks. Gateway-specific checkout and webhook endpoints are intentionally absent.
