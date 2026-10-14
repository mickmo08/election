"use client";
import { useState } from "react";
import { useApi } from "@/lib/useApi";
import { api, fmtDate, fmtInt } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AboutData, Empty, ErrorState, Loading, SyntheticBanner } from "@/components/States";
import { DataTable, LineChart } from "@/components/Charts";
import { PARTY_COLORS } from "@/components/Picker";

function Surveys() {
  const { can } = useAuth();
  const list = useApi<any>("/api/v1/surveys");
  const [ds, setDs] = useState("");
  const [row, setRow] = useState("");
  const [col, setCol] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const tab = useApi<any>(ds && row ? `/api/v1/surveys/${ds}/crosstab?row=${row}${col ? `&col=${col}` : ""}` : null);
  const dataset = list.data?.datasets.find((d: any) => d.id === ds);
  async function upload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    try {
      const r = await api<any>("/api/v1/surveys", { method: "POST", body: new FormData(e.currentTarget) });
      setMsg(`Imported ${r.rows} responses.`);
      list.reload();
    } catch (err: any) {
      setMsg(`Import rejected: ${err.message}`);
    }
  }
  return (
    <section>
      <h2>Survey microdata (your organization only)</h2>
      <p className="muted">Respondent-level data is never displayed or exported. Aggregates suppress small cells.</p>
      {list.data?.datasets.length === 0 && <Empty title="No survey datasets imported." />}
      {list.data && list.data.datasets.length > 0 && (
        <div className="filters">
          <label>Dataset<select value={ds} onChange={(e) => { setDs(e.target.value); setRow(""); setCol(""); }}>
            <option value="">Choose…</option>{list.data.datasets.map((d: any) => <option key={d.id} value={d.id}>{d.name} (n {d.n_rows_band})</option>)}</select></label>
          {dataset && <>
            <label>Rows<select value={row} onChange={(e) => setRow(e.target.value)}><option value="">—</option>
              {dataset.columns.map((c: string) => <option key={c}>{c}</option>)}</select></label>
            <label>Columns<select value={col} onChange={(e) => setCol(e.target.value)}><option value="">All respondents</option>
              {dataset.columns.map((c: string) => <option key={c}>{c}</option>)}</select></label></>}
        </div>
      )}
      {tab.error && <ErrorState error={tab.error} />}
      {tab.data && (
        <div className="table-wrap"><table>
          <caption>Weighted % by {tab.data.row_var}{tab.data.col_var ? ` × ${tab.data.col_var}` : ""} — {tab.data.uncertainty}</caption>
          <thead><tr><th scope="col">{tab.data.row_var}</th>{Object.keys(tab.data.columns).map((c) => <th scope="col" key={c} className="num">{c}</th>)}</tr></thead>
          <tbody>{Array.from(new Set(Object.values(tab.data.columns).flatMap((c: any) => Object.keys(c.cells ?? {})))).map((v) => (
            <tr key={v}><th scope="row">{v || "(blank)"}</th>{Object.entries(tab.data.columns).map(([k, c]: [string, any]) => (
              <td key={k} className="num">{c.suppressed ? "suppressed" : c.cells[v]?.suppressed ? "<n" : `${c.cells[v]?.weighted_pct ?? "—"}%`}</td>))}</tr>))}
            <tr><th scope="row">Base (unweighted n)</th>{Object.entries(tab.data.columns).map(([k, c]: [string, any]) => <td key={k} className="num">{c.base_n_band ?? "<30"}</td>)}</tr>
          </tbody></table></div>
      )}
      {can("surveys:import") && (
        <form className="panel" onSubmit={upload}>
          <h3>Import de-identified survey (CSV)</h3>
          <div className="filters">
            <label>Name<input name="name" required /></label>
            <label>File<input name="file" type="file" accept=".csv" required /></label>
            <label>Sampling<select name="sampling_method">{["probability", "nonprobability", "mixed", "unknown"].map((s) => <option key={s}>{s}</option>)}</select></label>
            <label>Population<select name="population"><option value="a">All adults</option><option value="rv">Registered voters</option><option value="lv">Likely voters</option></select></label>
            <label>Weight column<input name="weight_column" /></label>
          </div>
          <label>Consent basis<input name="consent_basis" required minLength={20} /></label>
          <label>De-identification attestation<input name="deidentification_attestation" required minLength={20} /></label>
          <p><button type="submit">Import</button></p>
          {msg && <p role="status">{msg}</p>}
        </form>
      )}
    </section>
  );
}

export default function Polls() {
  const [country, setCountry] = useState("XS");
  const avg = useApi<any>(`/api/v1/polls/average?country=${country}`);
  const polls = useApi<any>(`/api/v1/polls?country=${country}&scope=generic_ballot`);
  return (
    <>
      <h1>Polling and surveys</h1>
      <label>Country<select value={country} onChange={(e) => setCountry(e.target.value)}>
        <option value="XS">Synthetic Federation (demo)</option><option value="US">United States</option></select></label>
      <SyntheticBanner show={country === "XS"} />
      {avg.loading && <Loading />}
      {avg.error && <ErrorState error={avg.error} />}
      {avg.data && (!avg.data.available ? <Empty title="No eligible polls in the last 60 days.">{avg.data.reason}</Empty> : (
        <>
          <LineChart colors={PARTY_COLORS} title="Generic-ballot polling average" xLabel="As of" yUnit="%" description="weekly recomputation; not a forecast"
            series={Object.keys(avg.data.estimates).map((k) => ({ name: k, points: avg.data.trend.map((t: any) => ({ x: t.as_of, y: t[k] ?? null })) }))} />
          <DataTable caption={`Current average from ${avg.data.n_polls} polls`} columns={[{ key: "choice", label: "Choice" },
            { key: "mean", label: "Average", numeric: true, format: (v) => `${v}%` }, { key: "spread_sd", label: "Spread across polls (SD)", numeric: true, format: (v) => `${v} pts` },
            { key: "n_polls", label: "Polls", numeric: true }]}
            rows={Object.entries(avg.data.estimates).map(([k, v]: [string, any]) => ({ choice: k, ...v }))} />
          {avg.data.excluded.length > 0 && <details><summary>{avg.data.excluded.length} overlapping tracking releases excluded</summary>
            <ul>{avg.data.excluded.map((x: any) => <li key={x.poll_id}>{x.reason}</li>)}</ul></details>}
          <AboutData source="Published polls (registered sources)." period={`${avg.data.window_days} days to ${avg.data.as_of}`}
            metric={avg.data.method} limitations="Undecided shares are shown as published. The spread is not a margin of error." />
        </>
      ))}
      <h2>Polls</h2>
      {polls.data && (polls.data.polls.length === 0 ? <Empty title="No polls loaded." /> : (
        <div className="table-wrap"><table>
          <thead><tr><th scope="col">Pollster</th><th scope="col">Field dates</th><th scope="col">Population</th><th scope="col" className="num">n</th>
            <th scope="col">Mode / sampling</th><th scope="col">Uncertainty</th><th scope="col">Results</th></tr></thead>
          <tbody>{polls.data.polls.slice(0, 40).map((p: any) => (
            <tr key={p.id}><th scope="row">{p.pollster}{p.sponsor_is_partisan && <span className="badge">partisan sponsor</span>}
              {p.tracking_series && <div className="muted">{p.tracking_series}</div>}</th>
              <td>{fmtDate(p.field_start)} – {fmtDate(p.field_end)}</td><td>{p.population_label}</td><td className="num">{fmtInt(p.sample_size)}</td>
              <td>{p.mode} / {p.sampling_method}</td><td>{p.uncertainty.label}</td>
              <td>{p.questions[0]?.results.map((r: any) => `${r.choice} ${r.pct}%`).join(", ")}
                <div className="muted"><a href={p.methodology_url}>methodology</a></div></td></tr>))}</tbody>
        </table></div>
      ))}
      <Surveys />
    </>
  );
}
