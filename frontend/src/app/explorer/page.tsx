"use client";
import { useState } from "react";
import Link from "next/link";
import { useApi } from "@/lib/useApi";
import { fmtInt, fmtPct } from "@/lib/api";
import { CountryCycle, PARTY_COLORS, useCountries } from "@/components/Picker";
import { AboutData, Empty, ErrorState, Loading, StatusBadge, SyntheticBanner } from "@/components/States";
import { DistrictMap } from "@/components/DistrictMap";
import { useAuth } from "@/lib/auth";

export default function Explorer() {
  const countries = useCountries();
  const { can } = useAuth();
  const [sel, setSel] = useState({ country: "XS", cycle: "2024", office: "xs_assembly" });
  const q = `country=${sel.country}&cycle=${sel.cycle}${sel.office ? `&office=${sel.office}` : ""}`;
  const contests = useApi<any>(`/api/v1/contests?${q}`);
  const map = useApi<any>(sel.office ? `/api/v1/map?${q}` : null);
  if (countries.error) return <ErrorState error={countries.error} />;
  if (!countries.data) return <Loading />;
  return (
    <>
      <h1>Contest and district explorer</h1>
      <CountryCycle countries={countries.data} country={sel.country} cycle={sel.cycle} office={sel.office}
        onChange={(country, cycle) => setSel({ country, cycle, office: "" })} onOffice={(office) => setSel({ ...sel, office })} />
      {contests.loading && <Loading />}
      {contests.error && <ErrorState error={contests.error} onRetry={contests.reload} />}
      {contests.data && (
        <>
          <SyntheticBanner show={contests.data.is_synthetic} />
          {map.data && map.data.features.length > 0 && (
            <>
              <DistrictMap features={map.data.features} colors={PARTY_COLORS} country={sel.country} />
              <p className="muted">Boundary plan(s): {map.data.plans.map((p: any) => `${p.name} (${p.boundary_status})`).join("; ")}
                {map.data.districts_without_geometry > 0 && ` — ${map.data.districts_without_geometry} districts have no loaded boundaries.`}</p>
            </>
          )}
          {map.data && map.data.features.length === 0 && sel.office && (
            <Empty title="No district boundaries loaded.">The map is unavailable until a boundary source is ingested; the table below is complete.</Empty>
          )}
          {contests.data.count === 0 ? (
            <Empty title="No contests for this selection.">Contests appear once a registered source loads them.</Empty>
          ) : (
            <div className="table-wrap"><table>
              <caption>{contests.data.count} contests</caption>
              <thead><tr><th scope="col">Contest</th><th scope="col">Status</th><th scope="col" className="num">Reporting</th>
                <th scope="col">Leader</th><th scope="col" className="num">Share</th><th scope="col">Runner-up</th>
                <th scope="col" className="num">Share</th><th scope="col" className="num">Margin (pts)</th><th scope="col" className="num">Votes</th></tr></thead>
              <tbody>{contests.data.contests.map((c: any) => (
                <tr key={c.id}>
                  <th scope="row"><Link href={`/contests/${c.id}`}>{c.name}</Link></th>
                  <td><StatusBadge status={c.status} /></td>
                  <td className="num">{c.reporting_pct === null ? "n/a" : fmtPct(c.reporting_pct, 0)}</td>
                  <td>{c.top[0] ? `${c.top[0].label} (${c.top[0].party ?? "—"})` : "—"}</td>
                  <td className="num">{fmtPct(c.top[0]?.share)}</td>
                  <td>{c.top[1] ? `${c.top[1].label} (${c.top[1].party ?? "—"})` : "—"}</td>
                  <td className="num">{fmtPct(c.top[1]?.share)}</td>
                  <td className="num">{c.margin_pct ?? "—"}</td><td className="num">{fmtInt(c.total_votes)}</td>
                </tr>))}
              </tbody>
            </table></div>
          )}
          {can("data:export") && contests.data.count > 0 && (
            <p><a href="#" onClick={async (e) => {
              e.preventDefault();
              const { api } = await import("@/lib/api");
              const res = await api<Response>(`/api/v1/exports/contests.csv?${q}`, { raw: true });
              const url = URL.createObjectURL(await res.blob());
              Object.assign(document.createElement("a"), { href: url, download: `contests-${sel.country}-${sel.cycle}.csv` }).click();
            }}>Download this table as CSV</a> <span className="muted">(metered export; recorded in the audit log)</span></p>
          )}
          <AboutData source="Result snapshots from registered sources (latest per contest)." period={`Cycle ${sel.cycle}`}
            metric={contests.data.metric_definitions.margin_pct + " " + contests.data.metric_definitions.reporting_pct}
            limitations="Shares include all listed lines (incl. write-ins). The leader is not a race call." />
        </>
      )}
    </>
  );
}
