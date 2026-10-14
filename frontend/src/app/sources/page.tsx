"use client";
import { useState } from "react";
import { useApi } from "@/lib/useApi";
import { fmtDate } from "@/lib/api";
import { ErrorState, Freshness, Loading } from "@/components/States";

export default function Sources() {
  const s = useApi<any>("/api/v1/sources");
  const [open, setOpen] = useState<string | null>(null);
  const runs = useApi<any>(open ? `/api/v1/sources/${open}/runs` : null);
  if (s.loading) return <Loading />;
  if (s.error) return <ErrorState error={s.error} />;
  return (
    <>
      <h1>Source registry</h1>
      <p className="muted">Every dataset shown in the platform comes from one of these registered sources. Unavailable sources are never
        replaced with invented data.</p>
      {s.data.sources.map((x: any) => (
        <section key={x.key} className="panel" aria-labelledby={`src-${x.key}`}>
          <h2 id={`src-${x.key}`}>{x.name} {x.is_synthetic && <span className="badge">SYNTHETIC</span>}</h2>
          <p><span className="badge">{x.status}</span> <Freshness f={x.freshness} /> {x.open_quarantine > 0 && <span className="badge fresh-stale">{x.open_quarantine} open quarantine items</span>}</p>
          {x.status !== "active" && <p className="banner warn"><strong>Unavailable:</strong> {x.status_reason} <br /><strong>Remediation:</strong> {x.remediation}</p>}
          <div className="about"><dl>
            <dt>Publisher</dt><dd>{x.publisher} · owner: {x.owner_team}</dd>
            <dt>Access</dt><dd>{x.access_method}: {x.access_details}</dd>
            <dt>Terms</dt><dd>{x.access_terms}</dd>
            <dt>Licence</dt><dd>{x.license} · redistribution {x.permits_redistribution ? "permitted" : "not permitted"} · text analysis {x.permits_text_analysis ? "permitted" : "not permitted"}</dd>
            <dt>Refresh</dt><dd>{x.refresh_schedule}{x.freshness_sla_hours ? ` (SLA ${x.freshness_sla_hours} h)` : ""}</dd>
            <dt>Reliability</dt><dd>{x.reliability_notes}</dd>
            <dt>Verification</dt><dd>{x.verification}</dd>
            <dt>Last success</dt><dd>{fmtDate(x.last_success_at)}</dd>
          </dl></div>
          <button className="link" onClick={() => setOpen(open === x.key ? null : x.key)} aria-expanded={open === x.key}>Ingestion runs</button>
          {open === x.key && runs.data && (runs.data.runs.length === 0 ? <p className="muted">No runs.</p> : (
            <div className="table-wrap"><table><thead><tr><th scope="col">Started</th><th scope="col">Status</th><th scope="col">Adapter</th><th scope="col">Stats / error</th></tr></thead>
              <tbody>{runs.data.runs.map((r: any) => <tr key={r.id}><th scope="row">{fmtDate(r.started_at)}</th><td>{r.status}</td>
                <td>{r.adapter} {r.version}</td><td><code>{r.error ?? JSON.stringify(r.stats)}</code></td></tr>)}</tbody></table></div>
          ))}
        </section>
      ))}
    </>
  );
}
