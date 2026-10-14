"""Closed-loop load generator for the documented workload (docs/operations/load-test.md).

Workload mix per virtual user iteration (weights):
  45  GET /api/v1/contests (explorer table, 40-row synthetic office)
  20  GET /api/v1/contests/{id} (contest detail with history)
  10  GET /api/v1/overview
  10  GET /api/v1/polls/average (includes weekly trend recomputation)
   5  GET /api/v1/issues/trends
   5  GET /api/v1/map
   5  POST /api/v1/assistant/query (offline deterministic provider)
Each virtual user authenticates once, then issues requests back-to-back with no think time
(a deliberately pessimistic closed loop).

Usage: python loadtest.py --base http://localhost:8000 --users 20 --duration 60 --out result.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from collections import defaultdict

import httpx

MIX = [("contests", 45), ("contest", 20), ("overview", 10), ("polls", 10), ("issues", 5), ("map", 5), ("assistant", 5)]
QUESTIONS = ["What were the 2024 results in NM-03 in the Synthetic Federation?",
             "What does the generic ballot polling average show for the Synthetic Federation?",
             "Which data sources are unavailable?"]


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    f, c = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


async def user(base: str, token: str, contest_ids: list[str], stop: float, lat: dict, errs: dict, rng: random.Random):
    h = {"authorization": f"Bearer {token}", "x-tenant": "demo-newsroom"}
    names, weights = zip(*MIX, strict=True)
    async with httpx.AsyncClient(base_url=base, headers=h, timeout=30) as c:
        while time.monotonic() < stop:
            kind = rng.choices(names, weights)[0]
            t0 = time.perf_counter()
            try:
                if kind == "contests":
                    r = await c.get("/api/v1/contests", params={"country": "XS", "cycle": "2024", "office": "xs_assembly"})
                elif kind == "contest":
                    r = await c.get(f"/api/v1/contests/{rng.choice(contest_ids)}")
                elif kind == "overview":
                    r = await c.get("/api/v1/overview", params={"country": "XS", "cycle": "2024"})
                elif kind == "polls":
                    r = await c.get("/api/v1/polls/average", params={"country": "XS"})
                elif kind == "issues":
                    r = await c.get("/api/v1/issues/trends", params={"country": "XS", "weeks": 12})
                elif kind == "map":
                    r = await c.get("/api/v1/map", params={"country": "XS", "cycle": "2024", "office": "xs_assembly"})
                else:
                    r = await c.post("/api/v1/assistant/query", json={"question": rng.choice(QUESTIONS)})
                ok = r.status_code < 400
            except httpx.HTTPError:
                ok = False
            dt = (time.perf_counter() - t0) * 1000
            lat[kind].append(dt)
            if not ok:
                errs[kind] += 1


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--out")
    a = ap.parse_args()
    async with httpx.AsyncClient(base_url=a.base) as c:
        tok = (await c.post("/api/v1/dev/token", json={"subject": "demo-analyst"})).json()["token"]
        h = {"authorization": f"Bearer {tok}", "x-tenant": "demo-newsroom"}
        ids = [x["id"] for x in (await c.get("/api/v1/contests", headers=h, params={
            "country": "XS", "cycle": "2024", "office": "xs_assembly"})).json()["contests"]]
    lat: dict[str, list[float]] = defaultdict(list)
    errs: dict[str, int] = defaultdict(int)
    start = time.monotonic()
    stop = start + a.duration
    await asyncio.gather(*(user(a.base, tok, ids, stop, lat, errs, random.Random(i)) for i in range(a.users)))
    elapsed = time.monotonic() - start
    allv = [v for xs in lat.values() for v in xs]
    report = {
        "users": a.users, "duration_s": round(elapsed, 1), "requests": len(allv),
        "throughput_rps": round(len(allv) / elapsed, 1), "errors": sum(errs.values()),
        "error_rate": round(sum(errs.values()) / max(1, len(allv)), 5),
        "overall_ms": {"p50": round(pct(allv, .5), 1), "p95": round(pct(allv, .95), 1), "p99": round(pct(allv, .99), 1)},
        "by_endpoint": {k: {"n": len(v), "errors": errs[k], "p50_ms": round(pct(v, .5), 1), "p95_ms": round(pct(v, .95), 1),
                            "mean_ms": round(statistics.fmean(v), 1)} for k, v in sorted(lat.items())},
    }
    print(json.dumps(report, indent=2))
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(report, fh, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
