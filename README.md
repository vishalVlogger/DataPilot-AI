# DataPilot AI

DataPilot AI is a working MVP for uploading CSV/Excel datasets, profiling their contents, and asking deterministic natural-language questions. Calculations are performed with Pandas; the AI provider only interprets supported intent.

## Architecture

- `backend/app/api/routes`: small HTTP route handlers
- `backend/app/services/datasets`: validated file parsing and local dataset storage
- `backend/app/services/analytics`: profiling and safe query-plan execution
- `backend/app/services/ai`: provider abstraction and offline `MockAIProvider`
- `frontend/src`: Next.js App Router UI and typed API client

Uploaded files are assigned UUIDs and stored beneath the configured data directory. Paths and raw internal models are never returned to clients.

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

Column matching is case-insensitive and tolerates spaces/underscores. Ambiguous or unsupported questions return a clear error instead of fabricated values.

## API

- `GET /api/health`
- `POST /api/datasets/upload` (multipart file, optional `sheet_name` and `header_row`)
- `POST /api/datasets/inspect` (Excel worksheet discovery)
- `GET /api/datasets/{dataset_id}`
- `GET /api/datasets/{dataset_id}/profile`
- `POST /api/datasets/{dataset_id}/ask`

## Current scope

This milestone includes upload, worksheet selection, profiling, summary UI, offline mock AI, and deterministic total/average/min/max/count/top-N/bottom-N queries. Automatic insights, charts, cleaning, quality workflows, persistence in PostgreSQL, and exports are reserved for the next milestone.
