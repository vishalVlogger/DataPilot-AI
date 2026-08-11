"""Practical Parquet/DuckDB benchmark for Milestone 4.

Run from backend/: python scripts/benchmark_storage.py
"""
import asyncio
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.dataset import AnalysisPlan
from app.services.analytics.engines.duckdb_engine import DuckDBExecutionEngine


async def benchmark(rows: int) -> dict:
    generator = np.random.default_rng(42)
    frame = pd.DataFrame({
        "Region": generator.choice(["North", "South", "East", "West"], rows),
        "Product": generator.choice(["Alpha", "Beta", "Gamma", "Delta"], rows),
        "Sales": generator.integers(1, 10_000, rows),
        "Date": pd.date_range("2024-01-01", periods=rows, freq="min"),
    })
    with TemporaryDirectory() as directory:
        path = Path(directory) / "dataset.parquet"
        started = perf_counter(); frame.to_parquet(path, compression="zstd", index=False); write_ms = (perf_counter() - started) * 1000
        plan = AnalysisPlan(operation="group_and_aggregate", metric="Sales", aggregation="sum", group_by=["Region"], sort="desc")
        started = perf_counter(); result = await DuckDBExecutionEngine().execute_plan(path, plan); query_ms = (perf_counter() - started) * 1000
        started = perf_counter(); loaded = pd.read_parquet(path); pandas_load_ms = (perf_counter() - started) * 1000
        return {
            "rows": rows, "parquet_mb": round(path.stat().st_size / 1024 / 1024, 2),
            "write_ms": round(write_ms, 2), "direct_duckdb_query_ms": round(query_ms, 2),
            "pandas_full_load_ms": round(pandas_load_ms, 2), "pandas_memory_mb": round(loaded.memory_usage(deep=True).sum() / 1024 / 1024, 2),
            "result_groups": len(result.result),
        }


async def main() -> None:
    print(json.dumps([await benchmark(rows) for rows in (100_000, 500_000)], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
