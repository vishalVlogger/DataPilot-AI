# DataPilot AI

DataPilot AI is a working local-first application for uploading CSV/Excel datasets, profiling and versioning their contents, asking deterministic natural-language questions, discovering insights, generating charts, and downloading analysis reports. Calculations run through validated Pandas or DuckDB engines; AI providers only interpret intent and explain calculated results.

## Architecture

- `backend/app/api/routes`: small HTTP route handlers
- `backend/app/services/datasets`: validated file parsing and local dataset storage
- `backend/app/services/analytics`: profiling and safe query-plan execution
- `backend/app/services/analytics/engines`: async Pandas/DuckDB execution abstraction and threshold selector
- `backend/app/services/cleaning`: preview-first, confirmed cleaning operations
- `backend/app/services/visualization`: calculated chart-data generation
- `backend/app/services/reports`: escaped, real-value HTML report generation
- `backend/app/services/ai`: offline Mock plus optional Ollama/OpenAI providers
- `frontend/src`: Next.js App Router UI and typed API client

Uploaded files are assigned UUIDs and stored beneath the configured data directory. Version 0 is immutable; every confirmed cleaning or restore creates a numbered version and updates the working pointer. Paths and raw internal models are never returned to clients.

## Run locally

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item ..\.env.example .env
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

## Test and build

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
- `GET /api/datasets/{dataset_id}/export?format=csv|xlsx&version=current|original`

## Analytics and safety

Query plans support aggregate, grouped aggregate, multiple filters/groups/sorts, relative dates, top/bottom N, distinct count, trends, comparisons, percent of total, contribution, rank, running total, percentage change, moving average, variance, correlation, consecutive growth/decline, segment comparison, and constrained pipelines. Supported aggregations are sum, average, median, min, max, and count. Plans and filters are validated against the dataset schema before execution; model-produced SQL or Python is never executed.

Small datasets use Pandas by default. Datasets at `DUCKDB_ROW_THRESHOLD` use DuckDB for safe application-generated queries. `FORCED_EXECUTION_ENGINE=pandas|duckdb` is available for development. `MAX_ANALYSIS_ROWS` provides a separate execution safety ceiling.

DuckDB natively executes validated filtering, sorting, aggregation, ranking, contribution, variance, trends, and ungrouped period comparisons. Windowed/pipeline operations that are not yet compiled to DuckDB use the reference Pandas implementation and report `pandas_fallback` in timing metadata.

Charts support bar, column, line, pie, and scatter output using Recharts. Chart values always come from the analytics executor.

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

Reports are generated as self-contained HTML with configurable profile, insight, quality, chart-summary, and version-history sections. All displayed values are calculated from the current dataset version. Report titles are escaped and download filenames are sanitized.

## Known limitations

- Mock intent parsing intentionally supports common phrasing rather than unrestricted language.
- Category-value inference samples at most 20 unique values per categorical column.
- Relative dates and period comparisons use standard calendar boundaries and the server clock.
- Storage and cleaning audit metadata are local filesystem based and intended for single-instance MVP use.
- Local version history currently stores a full Pickle snapshot per version; delta/object-storage versions are future work.
- PDF reports are not included; the report service is structured for a later PDF renderer.
- CSV/Excel ingestion still parses with Pandas before DuckDB execution; direct Parquet/DuckDB-backed ingestion is future work.
