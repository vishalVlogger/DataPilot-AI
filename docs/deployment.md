# Deployment readiness

## Required production configuration

Set `APP_ENV=production`, a random `SECRET_KEY` of at least 32 bytes, a PostgreSQL `DATABASE_URL`, the public `FRONTEND_URL`, and the same origin in `CORS_ORIGINS`. HTTPS is required in production because refresh cookies are emitted with `Secure`. Keep dataset storage on a persistent mounted volume; database backups do not contain the Parquet files.

Run `alembic upgrade head` before each application release. Revision `0002` creates SaaS tables and assigns pre-existing records to `LEGACY_WORKSPACE_ID`, preserving local data while preventing new users from claiming it.

## Containers

Copy `.env.example` to `.env`, replace secrets, then run:

```sh
docker compose up --build
```

The stack starts PostgreSQL, runs migrations, waits for `/api/ready`, and then starts the standalone Next.js server. Named volumes persist PostgreSQL and dataset files.

## Operations

- Liveness: `GET /api/health`
- Readiness: `GET /api/ready` verifies database connectivity and storage availability.
- Logs are newline-delimited JSON with request IDs, route, status, and duration.
- Back up the PostgreSQL database and dataset volume as one recovery unit.
- The bundled limiter is process-local. Use a gateway or Redis-backed distributed limiter when running multiple backend replicas.
- Background jobs run in-process. Use a durable worker queue before scaling backend replicas or requiring guaranteed job recovery.
- Terminate TLS at the ingress and preserve `X-Request-ID`.

## Security model

Passwords use Argon2. Access tokens are short-lived bearer JWTs; opaque refresh tokens are stored only in an HttpOnly, SameSite cookie and their hashes are rotated in the database. Every tenant query validates a workspace membership and filters by `workspace_id`; inaccessible resources return the same not-found response as missing resources.
