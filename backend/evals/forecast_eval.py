"""Forecast evaluation report: runs a gated forecast (which includes the time-respecting backtest)
and writes JSON + Markdown evidence.

Run: python -m evals.forecast_eval --country XS --office xs_assembly --cycle 2026
"""

from __future__ import annotations

import argparse
import json

from app.db import worker_session
from app.services.forecasting import service as fc


def fmt(x: float | None, d: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{d}f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default="XS")
    ap.add_argument("--office", default="xs_assembly")
    ap.add_argument("--cycle", type=int, default=2026)
    ap.add_argument("--json")
    ap.add_argument("--md")
    a = ap.parse_args()
    with worker_session() as db:
        run = fc.run_forecast(
            db, country=a.country, office_key=a.office, cycle_year=a.cycle, data_cutoff=None, created_by="forecast_eval"
        )
        bt, gates = run.backtest, run.gate_results
        report = {
            "run_id": str(run.id),
            "status": run.status,
            "data_cutoff": run.data_cutoff.isoformat(),
            "uses_synthetic_data": run.uses_synthetic_data,
            "gates": gates,
            "backtest": bt,
            "inputs": run.inputs_summary,
            "aggregate": run.aggregate_outputs,
        }
        db.rollback()  # evaluation only; nothing persisted
    lines = [
        f"# Forecast evaluation: {a.country} {a.office} {a.cycle}",
        "",
        f"Status: **{report['status']}** · data cutoff {report['data_cutoff']} · synthetic data: "
        f"{report['uses_synthetic_data']}",
        "",
        "## Publication gates",
        "",
    ]
    lines += [f"- {'PASS' if g['passed'] else 'FAIL'} `{g['gate']}` — {g['detail']}" for g in gates]
    lines += [
        "",
        f"## Backtest ({bt.get('method', '')})",
        "",
        "| Held-out cycle | Trained on | Brier model | Brier uniform swing | Brier persistence | Log loss model | "
        "MAE margin | 80% coverage | Seats pred. median (80%) | Seats actual |",
        "|" + "---|" * 10,
    ]
    for c in bt.get("cycles", []):
        s = c["scores"]
        lines.append(
            f"| {c['cycle']} | {', '.join(map(str, c['train_cycles']))} | {fmt(s['model']['brier'])} | "
            f"{fmt(s['uniform_swing']['brier'])} | {fmt(s['persistence']['brier'])} | "
            f"{fmt(s['model']['log_loss'])} | {fmt(s['model']['mae_margin'])} | "
            f"{fmt(s['model']['coverage_80'], 2)} | {c['seats_a_predicted_median']} "
            f"({c['seats_a_p10_p90'][0]}–{c['seats_a_p10_p90'][1]}) | {c['seats_a_actual']} |"
        )
    p = bt.get("pooled", {})
    lines += [
        "",
        "## Pooled",
        "",
        "| Method | Brier | Log loss | MAE margin | 80% coverage | n |",
        "|---|---|---|---|---|---|",
    ]
    for k, v in p.items():
        lines.append(
            f"| {k} | {fmt(v['brier'])} | {fmt(v['log_loss'])} | {fmt(v['mae_margin'])} | "
            f"{fmt(v['coverage_80'], 2)} | {v['n']} |"
        )
    lines += [
        "",
        f"Brier skill vs persistence: {fmt(bt.get('brier_skill_vs_persistence'))}; "
        f"vs uniform swing: {fmt(bt.get('brier_skill_vs_uniform_swing'))}.",
        "",
        "## Calibration (pooled)",
        "",
        "| Bin | n | Mean predicted | Observed |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {b['bin']} | {b['n']} | {b['mean_predicted']} | {b['observed_rate']} |"
        for b in bt.get("calibration", {}).get("bins", [])
    ]
    lines += ["", f"Expected calibration error: {bt.get('calibration', {}).get('ece')}", ""]
    md = "\n".join(lines)
    print(md)
    if a.json:
        json.dump(report, open(a.json, "w"), indent=2, default=str)
    if a.md:
        open(a.md, "w").write(md)


if __name__ == "__main__":
    main()
