# DataPilot staging operations

DataPilot 0.7 keeps local execution/storage for development and supports Redis workers plus private S3-compatible storage for staging. Run the API and worker from the same image; only the API runs Alembic migrations.

## Deployment

Set `APP_ENV=staging`, a strong `SECRET_KEY`, PostgreSQL `DATABASE_URL`, `REDIS_URL`, `JOB_EXECUTION_MODE=redis`, and SMTP settings. For object storage set `DATASET_STORAGE_BACKEND=s3` and all `S3_*` values. Buckets must be private; the application does not set public ACLs. Deploy behind Caddy, Nginx, or a managed HTTPS proxy. The production container disables Uvicorn proxy-header handling by default. Set `TRUST_PROXY_HEADERS=true` only when the application is reachable solely through that trusted proxy; the application then installs its proxy-header middleware. Secure refresh cookies require HTTPS.

Use GitHub encrypted secrets or the deployment platform's secret manager. Never commit `.env`, SMTP passwords, Redis credentials, JWT secrets, API keys, or S3 keys.

## Validation

Run `python -m app.cli test-database`, `test-redis`, `test-storage`, `test-email user@example.com`, `test-sentry`, `verify-storage`, `staging-smoke`, and `production-readiness`. `migrate-storage --from local --to s3 --dry-run` is non-destructive; the migration never deletes local files. Repeat without `--dry-run` after reviewing its report.

## Backup and restore

Back up PostgreSQL with `pg_dump` and test `pg_restore`. Back up the complete local storage root, or enable S3 versioning and lifecycle policies. Storage includes datasets, reports, exports, and feedback attachments. `backup-manifest` creates inventory metadata only; it does not create a database backup.

Recovery order: restore PostgreSQL; restore objects; configure environment; run `alembic upgrade head`; run `verify-storage`; run `staging-smoke`; verify System Admin Health and Jobs.

Workspace owners can queue a portable ZIP export and schedule deletion from Settings. A scheduled workspace is read-only during the grace period. Redis workers process due deletion records every minute; an operator can also run `python -m app.cli process-deletions`. Account deletion is password-confirmed and is completed only after owned workspaces are gone and the same grace period has elapsed.

## Workers and load tests

Start a worker with `python -m app.worker`. It publishes a Redis heartbeat, promotes delayed retries, and consumes idempotent report/export jobs. Small beta: 5 users for 5 minutes. Moderate: 25 users for 10 minutes. Stress: 100 users only in an isolated environment. Run `python scripts/load_test.py --token ... --workspace ...`; laptop results are not production capacity claims.

Request bodies are never logged. In particular, login, registration, password reset, invitation acceptance, uploads, and feedback attachments must remain excluded. Logs and alerts must not include passwords, tokens, credentials, file contents, or dataset rows.
