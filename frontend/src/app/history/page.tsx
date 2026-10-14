"use client";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useApi } from "@/lib/useApi";
import { fmtPct } from "@/lib/api";
import { AboutData, Empty, ErrorState, Loading } from "@/components/States";
import { LineChart } from "@/components/Charts";
import { PARTY_COLORS } from "@/components/Picker";

function History() {
  const params = useSearchParams();
  const [district, setDistrict] = useState(params.get("district") ?? "");
  const contests = useApi<any>("/api/v1/contests?country=XS&cycle=2024&office=xs_assembly");
  const h = useApi<any>(district ? `/api/v1/districts/${district}/history` : null);
  const comparable = h.data?.history.filter((r: any) => r.compatibility.comparable) ?? [];
  const parties = Array.from(new Set(comparable.flatMap((r: any) => r.lines.map((l: any) => l.party)))) as string[];
  return (
    <>
      <h1>Historical comparison</h1>
      <p className="muted">Results are compared across cycles only when boundaries are identical or a population crosswalk exists.
        A matching district code alone is not treated as the same place.</p>
      <label>District (2024 plan)
        <select value={district} onChange={(e) => setDistrict(e.target.value)}>
          <option value="">Choose a district…</option>
          {contests.data?.contests.map((c: any) => <option key={c.district_id} value={c.district_id}>{c.district}</option>)}
        </select>
      </label>
      {!district && <Empty title="Choose a district to compare." />}
      {h.loading && <Loading />}
      {h.error && <ErrorState error={h.error} />}
      {h.data && (
        <>
          {comparable.length > 1 && (
            <LineChart colors={PARTY_COLORS} title={`Vote share in ${h.data.district.code}, comparable cycles only`} xLabel="Cycle" yUnit="%"
              series={parties.map((p) => ({ name: p, points: comparable.map((r: any) => ({ x: r.cycle,
                y: r.lines.find((l: any) => l.party === p)?.share ?? null })) }))} />
          )}
          <div className="table-wrap"><table>
            <thead><tr><th scope="col">Cycle</th><th scope="col">Status</th><th scope="col">Comparable?</th><th scope="col">Leading lines</th></tr></thead>
            <tbody>{h.data.history.map((r: any) => (
              <tr key={r.contest_id}><th scope="row"><Link href={`/contests/${r.contest_id}`}>{r.cycle}</Link></th><td>{r.status}</td>
                <td>{r.compatibility.comparable ? `Yes (${r.compatibility.basis.replace("_", " ")})` : "No"}
                  <div className="muted">{r.compatibility.detail}</div></td>
                <td>{r.lines.map((l: any) => `${l.label} (${l.party}) ${fmtPct(l.share)}`).join("; ")}</td></tr>))}</tbody>
          </table></div>
          <AboutData source="Final result snapshots; boundary plans and crosswalks from boundary sources."
            period="All loaded cycles" metric="Vote share by party line"
            limitations="Crosswalk-based comparisons approximate the old district's population; shown with the overlap share." />
        </>
      )}
    </>
  );
}

export default function Page() {
  return <Suspense fallback={<Loading />}><History /></Suspense>;
}
