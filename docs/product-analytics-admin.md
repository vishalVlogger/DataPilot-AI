# Product Analytics Admin Guide

System administrators can open `/admin/product`; workspace administrators cannot. Filters cover 7 days, 30 days, and all time.

The dashboard derives signup, verification, activation, return, D1/D7 retention, feature adoption, analysis success/failure categories, and usefulness ratings from metadata. Activation has one centralized meaning: verified email + first dataset + first successful analysis. Samples qualify for onboarding but do not consume dataset/storage quota.

The beta-user table recommends the next follow-up. Status changes and private notes are recorded in `system_admin_audit`. Notes must not contain customer data, passwords, tokens, or raw query results.

Product events use the taxonomy in `app/services/product_analytics.py`. Properties are allowlisted and writes are best-effort. Operational usage/billing logs remain separate.

Review failures and urgent feedback daily; funnel, retention, adoption, and usefulness weekly; and run the launch checklist plus full automated/Docker gates before releases.
