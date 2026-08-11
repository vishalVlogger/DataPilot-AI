# Milestone 4 storage benchmark

Run `python scripts/benchmark_storage.py` from `backend/` to reproduce the benchmark. It creates deterministic synthetic data, writes Zstandard-compressed Parquet, executes a grouped aggregate by scanning the Parquet file directly with DuckDB, and compares that query latency with the cost of fully materializing the file in pandas.

Results below were measured on the development Windows machine on 11 August 2026. They are practical smoke benchmarks, not universal performance guarantees.

| Rows | Parquet | Parquet write | Direct DuckDB query | Full pandas load | pandas memory |
|---:|---:|---:|---:|---:|---:|
| 100,000 | 1.05 MB | 195.94 ms | 188.84 ms | 50.63 ms | 11.75 MB |
| 500,000 | 4.50 MB | 314.92 ms | 127.17 ms | 77.38 ms | 58.77 MB |

For these narrow, highly compressible samples, a full pandas load is faster in raw latency, while direct DuckDB scanning avoids allocating the 11.75–58.77 MB pandas frame. DataPilot therefore keeps the configurable row-count threshold instead of claiming DuckDB wins every workload; the direct-scan path is intended to bound application memory as datasets widen and grow.
