"""Lightweight staging load test. Never use against production without approval."""
import argparse, asyncio, statistics, time
import httpx

async def user(base: str, token: str, workspace: str, duration: int, samples: list[float], errors: list[str]):
    headers={"Authorization":f"Bearer {token}","X-Workspace-ID":workspace}; end=time.monotonic()+duration
    async with httpx.AsyncClient(base_url=base,headers=headers,timeout=30) as client:
        while time.monotonic()<end:
            started=time.perf_counter()
            try:
                response=await client.get("/api/datasets?limit=25"); response.raise_for_status()
            except Exception as exc: errors.append(str(exc))
            samples.append((time.perf_counter()-started)*1000)

async def main(args):
    samples=[]; errors=[]; started=time.monotonic(); await asyncio.gather(*(user(args.base,args.token,args.workspace,args.seconds,samples,errors) for _ in range(args.users)))
    ordered=sorted(samples); percentile=lambda p: ordered[min(len(ordered)-1,int(len(ordered)*p))] if ordered else 0
    print({"requests":len(samples),"errors":len(errors),"throughput_rps":round(len(samples)/max(1,time.monotonic()-started),2),"p50_ms":round(percentile(.5),2),"p95_ms":round(percentile(.95),2),"p99_ms":round(percentile(.99),2)})

if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--base",default="http://localhost:8000"); parser.add_argument("--token",required=True); parser.add_argument("--workspace",required=True); parser.add_argument("--users",type=int,default=5); parser.add_argument("--seconds",type=int,default=300); asyncio.run(main(parser.parse_args()))
