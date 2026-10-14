"use client";
import { useState } from "react";
import { useApi } from "@/lib/useApi";
import { api, fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AboutData, Empty, ErrorState, Loading, SyntheticBanner } from "@/components/States";
import { BarChart, DataTable } from "@/components/Charts";

function RunDetail({ id }: { id: string }) {
  const { can } = useAuth();
  const r = useApi<any>(`/api/v1/forecasts/${id}`);
  const [msg, setMsg] = useState<string | null>(null);
  if (r.loading) return <Loading />;
  if (r.error) return <ErrorState error={r.error} />;
  const run = r.data;
  const agg = run.aggregate_outputs;
  return (
    <div className="panel">
      <h2>{run.kind === "scenario" ? "Scenario (not a forecast)" : "Forecast"} · {run.country} {run.office} {run.cycle} · <span className="badge">{run.status}</span></h2>
      <SyntheticBanner show={run.uses_synthetic_data} />
      <p className="muted">Model {run.model_version?.version} · data cutoff {fmtDate(run.data_cutoff)} · seed {run.random_seed} · created {fmtDate(run.created_at)}</p>
      <h3>Publication gates</h3>
      <ul>{run.gate_results.map((g: any) => <li key={g.gate} className={g.passed ? "gate-pass" : "gate-fail"}><strong>{g.gate}</strong>: {g.detail}</li>)}</ul>
      {run.status !== "published" && <div className="banner warn"><strong>Not published.</strong> {run.withheld_reason ?? "Outputs are shown to platform operators for review only."}</div>}
      {agg && (
        <>
          <p>Party A ({agg.party_a}) seats: median <strong>{agg.seats_a.median}</strong>, 80% interval {agg.seats_a.p10}–{agg.seats_a.p90}
            {agg.p_a_majority !== null && <> · probability of majority {(agg.p_a_majority * 100).toFixed(0)}%</>}. <span className="muted">{agg.dependence}</span></p>
          <BarChart title="Simulated seat distribution (share of simulations)" rows={agg.distribution.map((d: any) => ({ seats: `${d.seats} seats`, pct: +(d.share * 100).toFixed(1) }))}
            labelKey="seats" valueKey="pct" unit="%" />
          <DataTable caption="Contest estimates (two-party margin A−B)" columns={[{ key: "district_code", label: "District" },
            { key: "mean", label: "Mean margin", numeric: true, format: (v) => (v * 100).toFixed(1) },
            { key: "interval_80", label: "80% interval", format: (v) => `${(v[0] * 100).toFixed(1)} to ${(v[1] * 100).toFixed(1)}` },
            { key: "p_a", label: "P(A wins)", numeric: true, format: (v) => `${(v * 100).toFixed(0)}%` }, { key: "flags", label: "Flags", format: (v) => v.join(", ") }]}
            rows={run.contest_outputs} />
        </>
      )}
      <h3>Backtest (held-out cycles, time-respecting)</h3>
      <p className="muted">{run.backtest?.method}</p>
      {run.backtest?.cycles?.length ? (
        <DataTable columns={[{ key: "cycle", label: "Held-out cycle" }, { key: "train", label: "Trained on" },
          { key: "model", label: "Brier (model)", numeric: true }, { key: "swing", label: "Brier (uniform swing)", numeric: true },
          { key: "persist", label: "Brier (persistence)", numeric: true }, { key: "seats", label: "Seats predicted (80%) vs actual" }]}
          rows={run.backtest.cycles.map((c: any) => ({ cycle: c.cycle, train: c.train_cycles.join(", "),
            model: c.scores.model.brier?.toFixed(3), swing: c.scores.uniform_swing.brier?.toFixed(3), persist: c.scores.persistence.brier?.toFixed(3),
            seats: `${c.seats_a_predicted_median} (${c.seats_a_p10_p90.join("–")}) vs ${c.seats_a_actual}` }))} />
      ) : <Empty title="No backtest available." />}
      {run.backtest?.calibration && <DataTable caption={`Calibration (ECE ${run.backtest.calibration.ece})`} columns={[{ key: "bin", label: "Predicted bin" },
        { key: "n", label: "n", numeric: true }, { key: "mean_predicted", label: "Mean predicted", numeric: true }, { key: "observed_rate", label: "Observed", numeric: true }]}
        rows={run.backtest.calibration.bins} />}
      <h3>Assumptions</h3>
      <ul>{run.assumptions.map((a: string) => <li key={a}>{a}</li>)}</ul>
      {can("forecasts:publish") && run.kind === "forecast" && run.status !== "published" && (
        <button onClick={async () => { try { await api(`/api/v1/admin/forecasts/${id}/publish`, { method: "POST" }); r.reload(); }
          catch (e: any) { setMsg(e.message); } }}>Publish</button>)}
      {msg && <p role="alert">{msg}</p>}
    </div>
  );
}

export default function Forecasts() {
  const { can } = useAuth();
  const [country, setCountry] = useState("XS");
  const runs = useApi<any>(`/api/v1/forecasts?country=${country}`);
  const [sel, setSel] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <h1>Forecasts and methodology</h1>
      <p>Forecasts are statistical estimates built from documented methods and validated on held-out past elections. They are never
        produced by the AI assistant, never certain, and are published only when every gate passes.</p>
      <details className="panel"><summary>Methodology summary</summary>
        <p>District two-party margin = OLS on last boundary-compatible result, incumbency and the change in the national poll environment.
          Uncertainty combines a shared national error (Student-t, estimated from leave-one-cycle-out residuals) and district error, simulated
          10,000 times to produce seat distributions, so contests move together as they do in real elections. Baselines: persistence and
          uniform swing. See docs/methodology/forecasting.md.</p></details>
      <label>Country<select value={country} onChange={(e) => { setCountry(e.target.value); setSel(null); }}>
        <option value="XS">Synthetic Federation (demo)</option><option value="US">United States</option></select></label>
      {can("forecasts:run") && (
        <p><button className="secondary" onClick={async () => {
          const body = country === "XS" ? { country, office: "xs_assembly", cycle: 2026 } : { country, office: "us_house", cycle: 2026 };
          const j = await api<any>("/api/v1/admin/forecasts", { method: "POST", body: JSON.stringify(body) });
          setMsg(`Forecast job ${j.job_id} queued; the worker will add a run shortly.`);
        }}>Run forecast (queued job)</button> {msg && <span role="status">{msg}</span>}</p>
      )}
      {runs.loading && <Loading />}
      {runs.error && <ErrorState error={runs.error} />}
      {runs.data && (runs.data.runs.length === 0 ? (
        <Empty title="No forecast runs.">{country === "US" ? "U.S. forecasting is unavailable until verified historical results, district boundaries and contest lists are ingested." : ""}</Empty>
      ) : (
        <div className="table-wrap"><table>
          <thead><tr><th scope="col">Run</th><th scope="col">Kind</th><th scope="col">Status</th><th scope="col">Data cutoff</th><th scope="col">Gates</th></tr></thead>
          <tbody>{runs.data.runs.map((r: any) => (
            <tr key={r.id}><th scope="row"><button className="link" onClick={() => setSel(r.id)}>{r.office} {r.cycle} · {fmtDate(r.created_at)}</button></th>
              <td>{r.kind}</td><td>{r.status}</td><td>{fmtDate(r.data_cutoff)}</td>
              <td>{r.gate_results.filter((g: any) => g.passed).length}/{r.gate_results.length} passed</td></tr>))}</tbody>
        </table></div>
      ))}
      {sel && <RunDetail id={sel} />}
      <AboutData source="Final certified results, published polls (field end before cutoff), candidacies." period="Per run: data cutoff shown"
        metric="Two-party margin, win probability, seat distribution" limitations="Two-party framing; historical results may include post-cutoff corrections." />
    </>
  );
}
