# DataPilot 0.8 Beta Launch Checklist

## Before inviting users

- Deploy `0.8.0-beta` and run `alembic upgrade head`; confirm migration `0007` is current.
- Confirm HTTPS, secure cookies, PostgreSQL, Redis worker health, private object storage, SMTP delivery, error monitoring, backups, and restore procedures.
- Confirm product events contain only allowlisted metadata—never questions, filenames, dataset values, or result rows.
- Create a dedicated system-admin account and verify `/admin/product` for 7 days, 30 days, and all time.
- Complete one browser journey: register, verify, sample/upload, analyze, chart, report/export, rate, feedback, sign out, and return.
- Test CSV/workbook uploads, a failed question, quota messaging, mobile navigation, invitation delivery, recovery, attachments, and report download.

## Controlled beta rollout

- Invite 5–10 users with an acquisition source and named follow-up owner.
- Remind users to avoid sensitive or regulated data unless approved and to review calculated results.
- Review activation and failure categories daily. Activation is verified email + first dataset + first successful analysis.
- Store contact notes in the audited private beta-note control; never include secrets or dataset values.

## Launch decision

- No critical authentication, isolation, data-loss, migration, worker, storage, or download defects remain.
- Telemetry failure does not fail product requests.
- At least three simulated user journeys pass, including one failure/recovery path.
- Rollback image, backup, incident owner, support channel, and status communication are ready.
