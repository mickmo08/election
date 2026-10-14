"use client";
import { useState } from "react";
import Link from "next/link";
import { useApi } from "@/lib/useApi";
import { fmtDate } from "@/lib/api";
import { CountryCycle, useCountries } from "@/components/Picker";
import { AboutData, Empty, ErrorState, Freshness, Loading, SyntheticBanner } from "@/components/States";
import { BarChart } from "@/components/Charts";

export default function Overview() {
  const countries = useCountries();
  const [sel, setSel] = useState<{ country: string; cycle: string }>({ country: "US", cycle: "2026" });
  const ov = useApi<any>(`/api/v1/overview?country=${sel.country}&cycle=${sel.cycle}`);
  if (countries.error) return <ErrorState error={countries.error} />;
  if (!countries.data) return <Loading />;
  const d = ov.data;
  const unavailable = d?.sources.filter((s: any) => s.status !== "active") ?? [];
  return (
    <>
      <h1>Election overview</h1>
      <CountryCycle countries={countries.data} country={sel.country} cycle={sel.cycle}
        onChange={(country, cycle) => setSel({ country, cycle })} />
      {ov.loading && <Loading />}
      {ov.error && <ErrorState error={ov.error} onRetry={ov.reload} />}
      {d && (
        <>
          <SyntheticBanner show={d.country.is_synthetic} />
          {unavailable.length > 0 && (
            <div className="banner warn" role="note">
              <strong>{unavailable.length} data source(s) for {d.country.name} are not connected.</strong> Views that depend on them
              show “unavailable” rather than substitute data. See the <Link href="/sources">source registry</Link> for remediation.
            </div>
          )}
          <section className="grid" aria-label="Key figures">
            <div className="stat"><div className="muted">Contests loaded</div><div className="value">{d.contest_count}</div></div>
            <div className="stat"><div className="muted">Contests with published results</div>
              <div className="value">{d.contest_count - (d.results_by_status.no_results ?? 0)}</div></div>
            <div className="stat"><div className="muted">Connected sources</div>
              <div className="value">{d.sources.length - unavailable.length} / {d.sources.length}</div></div>
          </section>
          <h2>Calendar</h2>
          {d.calendar.length === 0 ? <Empty title="No elections loaded for this cycle." /> : (
            <ul>{d.calendar.map((e: any, i: number) => (
              <li key={i}><strong>{e.kind}</strong> {e.admin_unit ? `(${e.admin_unit}) ` : ""}— {fmtDate(e.date)}{" "}
                <span className="muted">Basis: {e.basis}</span></li>))}</ul>
          )}
          <h2>Contests by office</h2>
          {d.contest_count === 0 ? (
            <Empty title="No contests are loaded for this cycle.">
              Contests are created only from registered sources (e.g. FEC filings, state election officials). Candidate lists
              and races are never hard-coded.
            </Empty>
          ) : (
            <BarChart title="Contests by office" rows={Object.entries(d.contests_by_office).map(([k, v]) => ({ office: k, n: v }))}
              labelKey="office" valueKey="n" />
          )}
          <h2>Data sources</h2>
          <div className="table-wrap"><table>
            <thead><tr><th scope="col">Source</th><th scope="col">Kind</th><th scope="col">Status</th><th scope="col">Freshness</th><th scope="col">Remediation</th></tr></thead>
            <tbody>{d.sources.map((s: any) => (
              <tr key={s.key}><th scope="row">{s.name}</th><td>{s.data_kind}</td><td>{s.status}</td>
                <td><Freshness f={s.freshness} /></td><td className="muted">{s.status === "active" ? "" : s.remediation || s.status_reason}</td></tr>
            ))}</tbody>
          </table></div>
          <AboutData source="Registered sources listed above; election dates from cited statutory rules or sources."
            period={`Cycle ${d.cycle}; generated ${fmtDate(d.generated_at)}`}
            metric="Counts of contests and result snapshots in the platform database."
            limitations="Only contests loaded from registered sources appear. Missing sources are shown as unavailable." />
        </>
      )}
    </>
  );
}
