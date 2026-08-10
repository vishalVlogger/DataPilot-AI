# DataPilot AI

DataPilot AI is a working local-first MVP for uploading CSV/Excel datasets, profiling and cleaning their contents, asking deterministic natural-language questions, discovering insights, and generating charts. Calculations are performed with Pandas; the AI provider only interprets supported intent.

## Architecture

- `backend/app/api/routes`: small HTTP route handlers
- `backend/app/services/datasets`: validated file parsing and local dataset storage
- `backend/app/services/analytics`: profiling and safe query-plan execution
- `backend/app/services/cleaning`: preview-first, confirmed cleaning operations
- `backend/app/services/visualization`: calculated chart-data generation
- `backend/app/services/ai`: provider abstraction and offline `MockAIProvider`
- `frontend/src`: Next.js App Router UI and typed API client

Uploaded files are assigned UUIDs and stored beneath the configured data directory. The original parsed upload and current working version are kept separately, so confirmed cleaning can be reset safely. Paths and raw internal models are never returned to clients.

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

Column matching is case-insensitive and tolerates spaces/underscores. Ambiguous or unsupported questions return a clear error instead of fabricated values.

## API

- `GET /api/health`
- `POST /api/datasets/upload` (multipart file, optional `sheet_name` and `header_row`)
- `POST /api/datasets/inspect` (Excel worksheet discovery)
- `GET /api/datasets/{dataset_id}`
- `GET /api/datasets/{dataset_id}/profile`
- `POST /api/datasets/{dataset_id}/ask`
- `GET /api/datasets/{dataset_id}/insights`
- `POST /api/datasets/{dataset_id}/chart`
- `GET /api/datasets/{dataset_id}/quality`
- `POST /api/datasets/{dataset_id}/clean/preview`
- `POST /api/datasets/{dataset_id}/clean/apply` (`confirmed: true` required)
- `POST /api/datasets/{dataset_id}/reset`
- `GET /api/datasets/{dataset_id}/export?format=csv|xlsx&version=current|original`

## Analytics and safety

Query plans support aggregate, grouped aggregate, structured filters, sorting, top/bottom N, count, distinct count, trends, group comparison, and calendar-period comparison. Supported aggregations are sum, average, median, min, max, and count. Plans and filters are validated against the dataset schema before execution; model-produced code is never executed.

Charts support bar, column, line, pie, and scatter output using Recharts. Chart values always come from the analytics executor.

Cleaning supports duplicate removal, whitespace trimming, lower/upper/title case, missing-row removal, numeric mean/median fill, and explicit-value fill. Preview does not mutate the dataset. Apply requires explicit confirmation and records an audit entry.

## Known limitations

- Mock intent parsing intentionally supports common phrasing rather than unrestricted language.
- Category-value inference samples at most 20 unique values per categorical column.
- Period comparisons use standard calendar month, quarter, and year boundaries.
- Storage and cleaning audit metadata are local filesystem based and intended for single-instance MVP use.
- Large-file processing remains subject to configured Pandas row/column limits; streaming and distributed execution are future work.
