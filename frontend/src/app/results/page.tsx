"use client";
import { useState } from "react";
import Link from "next/link";
import { useApi } from "@/lib/useApi";
import { fmtDate, fmtInt } from "@/lib/api";
import { CountryCycle, useCountries } from "@/components/Picker";
import { AboutData, Empty, ErrorState, Loading, StatusBadge } from "@/components/States";
import { BarChart } from "@/components/Charts";

export default function Results() {
  const countries = useCountries();
  const [sel, setSel] = useState({ country: "XS", cycle: "2024" });
  const m = useApi<any>(`/api/v1/results/monitor?country=${sel.country}&cycle=${sel.cycle}`);
  if (!countries.data) return countries.error ? <ErrorState error={countries.error} /> : <Loading />;
  return (
    <>
      <h1>Results monitoring</h1>
      <CountryCycle countries={countries.data} country={sel.country} cycle={sel.cycle} onChange={(country, cycle) => setSel({ country, cycle })} />
      <button className="secondary" onClick={m.reload}>Refresh</button>
      {m.loading && <Loading />}
      {m.error && <ErrorState error={m.error} onRetry={m.reload} />}
      {m.data && (
        <>
          <p className="muted">{m.data.note}</p>
          <BarChart title="Contests by result status" rows={Object.entries(m.data.counts).map(([k, v]) => ({ status: k, n: v }))}
            labelKey="status" valueKey="n" />
          <dl className="panel">{Object.entries(m.data.status_definitions).map(([k, v]) => (
            <div key={k}><dt><StatusBadge status={k} /></dt><dd>{String(v)}</dd></div>))}</dl>
          <h2>Most recent updates</h2>
          {m.data.recent.length === 0 ? <Empty title="No results published yet for this cycle." /> : (
            <div className="table-wrap"><table>
              <thead><tr><th scope="col">Contest</th><th scope="col">Status</th><th scope="col" className="num">Reporting</th>
                <th scope="col" className="num">Votes</th><th scope="col">Retrieved</th></tr></thead>
              <tbody>{m.data.recent.map((r: any) => (
                <tr key={r.id}><th scope="row"><Link href={`/contests/${r.id}`}>{r.name}</Link></th><td><StatusBadge status={r.status} /></td>
                  <td className="num">{r.reporting_pct === null ? "not provided" : `${r.reporting_pct}%`}</td>
                  <td className="num">{fmtInt(r.total_votes)}</td><td>{fmtDate(r.retrieved_at)}</td></tr>))}</tbody>
            </table></div>
          )}
          <AboutData source="Latest snapshot per contest from registered results sources." period={`Cycle ${sel.cycle}`}
            metric="Snapshot status; reporting completeness only where the source publishes it." />
        </>
      )}
    </>
  );
}
