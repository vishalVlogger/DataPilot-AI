# DataPilot AI

DataPilot AI is a workspace-isolated SaaS application for uploading CSV/Excel datasets, profiling and versioning their contents, asking deterministic natural-language questions, discovering insights, generating charts, and downloading analysis reports. Calculations run through validated Pandas or DuckDB engines; AI providers only interpret intent and explain calculated results.

Profiles include semantic column roles in addition to physical dtypes. Measures, categorical/temporal/boolean dimensions, identifiers, and high-cardinality dimensions receive centralized aggregation and automatic-analysis policies so mathematically valid but meaningless calculations—such as summing a year or customer ID—are rejected.

## Architecture

- `backend/app/api/routes`: small HTTP route handlers
- `backend/app/services/datasets`: validated ingestion, Parquet versions, and lazy legacy migration
- `backend/app/models` and `repositories`: SQLAlchemy metadata, sessions, runs, saved analyses, and jobs
- `backend/app/services/analytics`: profiling and safe query-plan execution
- `backend/app/services/analytics/engines`: async Pandas/DuckDB execution abstraction and threshold selector
- `backend/app/services/cleaning`: preview-first, confirmed cleaning operations
- `backend/app/services/visualization`: calculated chart-data generation
- `backend/app/services/reports`: escaped, real-value HTML and ReportLab PDF generation
- `backend/app/services/jobs`: persistent background report jobs and progress stages
- `backend/app/services/ai`: offline Mock plus optional Ollama/OpenAI providers
- `frontend/src`: Next.js App Router UI and typed API client

Accounts use Argon2 passwords, short-lived JWT access tokens, rotating HttpOnly refresh cookies, and backend-validated workspace membership. Dataset metadata, versions, sessions, runs, saved analyses, jobs, reports, usage, and activity are all tenant-scoped.

Beta accounts support hashed, expiring, one-time email-verification and password-reset links through console or SMTP email providers. In local console mode, verification and invitation links are shown explicitly in the UI because no message is delivered; production SMTP responses never expose tokens. Password reset revokes every refresh session. Workspace owners/admins can invite verified users as admins or members, while system-administrator support access remains separate from workspace roles. The beta UI includes privacy acknowledgement, feedback with validated attachments, provider controls, account recovery, and metadata-only support tools.

Uploaded files are assigned UUIDs and normalized to Zstandard-compressed Parquet beneath the configured storage root. Version 0 is immutable; every confirmed cleaning or restore creates a numbered Parquet version and updates the database pointer. DuckDB scans supported plans directly from Parquet. Paths and raw internal models are never returned to clients.

## Run locally

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item ..\.env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

### Frontend

```powershell
cd frontend
npm install
Copy-Item .env.local.example .env.local
npm run dev
```

Open http://localhost:3000.

Register the first account in the UI. Its default workspace uses the Free plan; plan limits are enforced centrally by the backend. For a containerized PostgreSQL deployment, see [deployment readiness](docs/deployment.md).

## Test and build

System administrators use the dedicated `/admin` Platform Console for metadata-only platform operations. Workspace administrators manage one workspace and cannot access this console. See [System Admin Console](docs/admin.md) for routes, privacy boundaries, and audited CLI promotion.

```powershell
cd backend
python -m pytest

cd ..\frontend
npm run build
```

## Supported questions

- `What is the total revenue?`
- `Show average sales`
- `What is the minimum/maximum price?`
- `How many rows are there?`
- `Show top 5 products by revenue`
- `Show bottom 3 regions by sales`
- `Show sales by region`
- `Compare North and West sales`
- `Show monthly sales trend`
- `Which month had the highest revenue?`
- `Compare this month with the previous month`
- `Which product declined the most?`
- `Count unique customers`
- `Show revenue for July`
- `Show products where sales are above 100000`
- `Show West region sales above 50000 for the last 6 months grouped by product`
- `Show top 5 customers in each region`
- `Which products declined for 3 consecutive months?`
- `Show each region's contribution to total sales`
- `Rank products by revenue within each region`
- `Show a 3-month moving average of revenue`

Column matching is case-insensitive and tolerates spaces/underscores. Ambiguous or unsupported questions return a clear error instead of fabricated values.

## API

- `GET /api/health`
- `GET /api/ready`
- `POST /api/auth/register|login|refresh|logout`, `GET|PATCH /api/auth/me`
- `GET|POST /api/workspaces`, `GET|PATCH /api/workspaces/{workspace_id}`
- `GET /api/dashboard`, `/api/usage`, and `/api/activity`
- `GET /api/datasets` (workspace library with `search`, `source_type`, `recently_analyzed`, `limit`, and `offset`)
- `PATCH /api/datasets/{dataset_id}` (rename)
- `POST /api/datasets/upload` (multipart file, optional `sheet_name` and `header_row`)
- `POST /api/datasets/inspect` (Excel worksheet discovery)
- `GET /api/datasets/{dataset_id}`
- `GET /api/datasets/{dataset_id}/profile`
- `POST /api/datasets/{dataset_id}/ask`
- `POST /api/datasets/{dataset_id}/analyze` (validated plan input)
- `GET /api/datasets/{dataset_id}/insights`
- `POST /api/datasets/{dataset_id}/chart`
- `GET /api/datasets/{dataset_id}/quality`
- `POST /api/datasets/{dataset_id}/clean/preview`
- `POST /api/datasets/{dataset_id}/clean/apply` (`confirmed: true` required)
- `POST /api/datasets/{dataset_id}/reset`
- `GET /api/datasets/{dataset_id}/versions`
- `POST /api/datasets/{dataset_id}/versions/{version}/restore`
- `POST /api/datasets/{dataset_id}/report`
- `DELETE /api/datasets/{dataset_id}`
- `POST|GET /api/datasets/{dataset_id}/sessions`
- `GET /api/sessions/{session_id}` and `/runs`
- `POST|GET /api/datasets/{dataset_id}/saved-analyses`
- `POST /api/saved-analyses/{analysis_id}/run`
- `DELETE /api/saved-analyses/{analysis_id}`
- `POST /api/datasets/{dataset_id}/drilldown`
- `GET /api/jobs/{job_id}` and `/result`
- `GET /api/datasets/{dataset_id}/export?format=csv|xlsx&version=current|original`
- `GET /api/feedback/config`, `POST /api/feedback`, and `POST /api/feedback/{feedback_id}/attachments`
- `POST /api/workspaces/{workspace_id}/invitations/{invitation_id}/resend`

## Analytics and safety

Query plans support aggregate, grouped aggregate, multiple filters/groups/sorts, relative dates, top/bottom N, distinct count, trends, comparisons, percent of total, contribution, rank, running total, percentage change, moving average, variance, correlation, consecutive growth/decline, segment comparison, and constrained pipelines. Supported aggregations are sum, average, median, min, max, and count. Plans and filters are validated against the dataset schema before execution; model-produced SQL or Python is never executed.

Small datasets use Pandas by default. Datasets at `DUCKDB_ROW_THRESHOLD` use DuckDB for safe application-generated queries. `FORCED_EXECUTION_ENGINE=pandas|duckdb` is available for development. `MAX_ANALYSIS_ROWS` provides a separate execution safety ceiling.

DuckDB natively executes validated filtering, sorting, aggregation, ranking, contribution, variance, trends, and ungrouped period comparisons directly against Parquet. Windowed/pipeline operations that are not yet compiled to DuckDB use the reference Pandas implementation and report `pandas_fallback` in timing metadata.

Charts support bar, column, line, pie, and scatter output using Recharts. Chart values always come from the analytics executor.

Automatic chart selection follows semantic roles: temporal series use line charts, categorical and limited high-cardinality rankings use bars, and two-measure comparisons use scatter plots. Ranking questions expose the chosen metric, aggregation, direction, and limit; ambiguous rankings use a deterministic semantic default only when one can be justified and display that interpretation prominently. High-cardinality chart output is capped safely, while explicit technically valid chart-type overrides remain available.

### Semantic analysis

Semantic classification combines column names, physical types, uniqueness/cardinality, value patterns, plausible year ranges, and numeric variance. The profile exposes each column's role, confidence, uniqueness ratio, and allowed aggregations. The default UI keeps this under the expandable “Technical semantic profile” section.

- Measures allow meaningful numeric aggregation; the automatic policy prefers totals for additive metrics and averages for prices, rates, mileage, and similar measures.
- Temporal dimensions allow grouping, trends, counts, min, and max, but never automatic sums.
- Numeric calendar helpers such as month, quarter, and week numbers are recognized only when exact names and plausible value ranges agree. Named periods are paired with those helpers for chronological chart ordering.
- Identifiers allow counts/distinct counts and are not automatic measures.
- High-cardinality dimensions are excluded from automatic concentration, strongest/weakest, pie-chart, and aggressive category-variant analysis.
- Categorical/boolean distributions use row counts and one explicit, deduplicated most-common summary plus least-common context.

These same roles are included in Ollama/OpenAI schema context without sending dataset rows. HTML and PDF reports use semantic measures for summaries and semantic-aware automatic insights.

Cleaning supports duplicate removal, whitespace trimming, lower/upper/title case, missing-row removal, numeric mean/median fill, and explicit-value fill. Preview does not mutate the dataset. Apply requires explicit confirmation and records an audit entry.

## Optional AI providers

Mock mode remains the default and needs no external service:

```env
AI_PROVIDER=mock
```

Optional local Ollama:

```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5-coder:7b
```

Optional OpenAI:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
```

Provider output must validate as an `AnalysisPlan`. Provider failures fall back to Mock interpretation/explanation so deterministic analytics remain available. Only schema metadata, the validated plan, and calculated result are sent for interpretation/explanation—not the full dataset.

## Reports

Reports are generated as self-contained HTML or paginated PDF with configurable profile, insight, quality, chart-summary, and version-history sections. Generation may run synchronously or as a persistent background job with queued/running/completed/failed states and progress stages. All displayed values are calculated from the current dataset version. Report titles are escaped and download filenames are sanitized.

## Persistence and migration

SQLite is the zero-configuration default. Set `DATABASE_URL=postgresql+psycopg://user:password@host/database` for PostgreSQL, then run `alembic upgrade head`. SQLAlchemy stores dataset metadata, version pointers, analysis sessions/runs, saved plans, and jobs; dataset contents remain in Parquet.

Legacy Pickle datasets are migrated lazily on first access. Their existing files remain untouched while equivalent Parquet versions and database records are created. See [the reproducible 100k/500k benchmark](docs/milestone-4-benchmark.md) for measured storage, latency, and memory results.

## Known limitations

- Mock intent parsing intentionally supports common phrasing rather than unrestricted language.
- Category-value inference samples at most 20 unique values per categorical column.
- Relative dates and period comparisons use standard calendar boundaries and the server clock.
- Dataset contents and cleaning audit logs use local filesystem storage; an object-storage backend is a future extension of the storage interface.
- Each version is a full Parquet snapshot; delta versions and distributed job workers are future work.
- CSV/Excel ingestion still parses once with Pandas before normalization to Parquet.
- Semantic classification is deterministic and heuristic. Domain-specific concepts with ambiguous names may still need future user overrides or a semantic-metadata editor.
- Account and full-workspace deletion are admin-assisted during beta; individual dataset deletion remains self-service.
- Redis rate limiting is optional, while report execution still uses the local retry-safe executor. A distributed worker adapter is the next infrastructure step.
- The storage interface and tenant-scoped keys are cloud-ready, but this release ships only the local backend; S3-compatible configuration is reserved for the future adapter.
