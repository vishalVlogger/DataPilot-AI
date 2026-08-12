# Deployment readiness

## Required production configuration

Set `APP_ENV=production`, a random `SECRET_KEY` of at least 32 bytes, a PostgreSQL `DATABASE_URL`, the public `FRONTEND_URL`, and the same origin in `CORS_ORIGINS`. HTTPS is required in production because refresh cookies are emitted with `Secure`. Supply SMTP credentials through secrets and set `EMAIL_PROVIDER=smtp`; the console provider is for local development only. Set `SENTRY_DSN` only when the deployment is permitted to send scrubbed diagnostics to Sentry.

Run `alembic upgrade head` before each application release. Revision `0002` creates SaaS tables and assigns pre-existing records to `LEGACY_WORKSPACE_ID`, preserving local data while preventing new users from claiming it. Revision `0003` adds verification and recovery tokens, invitations, feedback, job retry metadata, and beta administration fields. Revision `0004` adds tenant-scoped feedback-attachment metadata. Revision `0005` adds feedback priority, grouped safe system-error summaries, and system-admin audit records.

Keep dataset storage on a persistent mounted volume; database backups do not contain Parquet files or feedback attachment bodies. Back up the complete storage root together with the database. `DATASET_STORAGE_BACKEND=local` is the supported backend in this release. The S3-compatible settings reserve the configuration contract for a future adapter and do not activate object storage yet.

## Containers

Copy `.env.example` to `.env`, replace secrets, then run:

```sh
docker compose up --build
```

The stack starts PostgreSQL, runs migrations, waits for `/api/ready`, and then starts the standalone Next.js server. Named volumes persist PostgreSQL and dataset files. Redis is optional and can be enabled with `docker compose --profile distributed up --build`; set `RATE_LIMIT_BACKEND=redis` at the same time. Do not select `JOB_EXECUTION_MODE=distributed` yet—the worker interface exists, but this release includes only the local executor.

## Operations

- Liveness: `GET /api/health`; readiness: `GET /api/ready` verifies database, storage, and configured Redis connectivity.
- Logs are newline-delimited JSON with request, user, workspace, and run correlation fields. Preserve `X-Request-ID` at the ingress and never place tokens, passwords, dataset rows, or raw prompts in logs.
- Back up PostgreSQL and the dataset/report volume as one recovery unit, encrypt backups, and regularly test a restore in an isolated environment.
- Run the retention cleanup from a trusted scheduler by calling the system-admin cleanup endpoint. Configure retention windows before enabling it and monitor the returned deletion counts.
- The Redis rate limiter coordinates multiple API replicas. The memory limiter is suitable only for a single process.
- Background jobs run in-process with bounded retries. Use a durable queue/worker implementation before scaling API replicas or requiring guaranteed recovery after restarts.
- Terminate TLS at the ingress, restrict admin routes, rotate secrets, and alert on readiness failures, elevated 5xx rates, and repeated authentication failures.

## Security model

Passwords use Argon2. Access tokens are short-lived bearer JWTs; opaque refresh tokens are stored only in an HttpOnly, SameSite cookie and their hashes are rotated in the database. Verification, reset, and invitation tokens are random, one-time, expiry-bound, and stored only as hashes. Every tenant query validates a workspace membership and filters by `workspace_id`; inaccessible resources return the same not-found response as missing resources.

Login is allowed before email verification so users can finish onboarding. Workspace invitations and externally hosted AI providers require verified email. Local deterministic analytics, local Ollama, and local report generation remain available. Workspace owners must explicitly enable external AI, and the provider-status endpoint explains the effective policy without exposing credentials.

System administration is separate from workspace roles. Use `python -m app.cli make-system-admin admin@example.com` or `python -m app.cli remove-system-admin admin@example.com` on a trusted application host; there is intentionally no public elevation endpoint. The CLI requires an existing account, never changes its password, writes an audit record, and protects the last active administrator. Support lookup and `/admin` return metadata only, never dataset rows. See [System Admin Console](admin.md).

## Beta rollout

Use `REGISTRATION_MODE=open` for public beta registration or `invite_only` to require a valid invitation. `BETA_MAX_USERS` is a simple registration cap and is not a substitute for an admission system under concurrent high load. Publish the beta notice and privacy terms represented by `BETA_NOTICE`, and keep `BETA_REGISTRATION_ENABLED=false` as the operational kill switch.

Feature flags default to the behavior documented in `.env.example`. Test disabled paths before deployment. Removing a member does not currently delete their account, and beta data deletion is an administrator-assisted process. A durable distributed job queue, an S3 storage adapter, automated user-data export/deletion, and richer alert routing remain post-beta work.

In `EMAIL_PROVIDER=console` with `APP_ENV=development|local|test`, registration and invitation responses intentionally include development-only links for copying or opening in the local UI. Console mode does not deliver email. Never use console mode in production. SMTP mode returns only provider acceptance/failure status and never returns a verification, reset, or invitation token. Admin diagnostics expose provider configuration and safe delivery status without credentials or recipient data.
