"use client";
import { useState } from "react";
import { api, fmtDate } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { useAuth } from "@/lib/auth";
import { DataTable } from "@/components/Charts";
import { Empty, ErrorState } from "@/components/States";

function Quarantine() {
  const q = useApi<any>("/api/v1/admin/quarantine?status=open");
  const [note, setNote] = useState("");
  if (q.error) return <ErrorState error={q.error} />;
  if (!q.data) return null;
  return (
    <section><h2>Data quarantine</h2>
      {q.data.items.length === 0 ? <Empty title="No open quarantine items." /> : (
        <div className="table-wrap"><table><thead><tr><th scope="col">Rule</th><th scope="col">Source</th><th scope="col">Record</th><th scope="col">Problem</th><th scope="col">Action</th></tr></thead>
          <tbody>{q.data.items.slice(0, 50).map((i: any) => (
            <tr key={i.id}><th scope="row">{i.rule} <span className="badge">{i.severity}</span></th><td>{i.source}</td><td>{i.record_ref}</td>
              <td>{i.message}<div className="muted">{i.suggested_action}</div></td>
              <td>{["accepted", "rejected", "fixed"].map((r) => <button key={r} className="secondary" disabled={note.length < 5}
                onClick={async () => { await api(`/api/v1/admin/quarantine/${i.id}/resolve`, { method: "POST", body: JSON.stringify({ resolution: r, note }) }); q.reload(); }}>{r}</button>)}</td></tr>))}</tbody>
        </table></div>)}
      <label>Resolution note (required, min 5 characters)<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
    </section>
  );
}

function Ops() {
  const s = useApi<any>("/api/v1/admin/ops/status");
  const jobs = useApi<any>("/api/v1/admin/jobs?status=dead");
  if (s.error) return <ErrorState error={s.error} />;
  return (
    <section><h2>Operations</h2>
      {s.data && <DataTable caption="Queue" columns={[{ key: "k", label: "Job status" }, { key: "v", label: "Count", numeric: true }]}
        rows={Object.entries(s.data.jobs).map(([k, v]) => ({ k, v }))} />}
      {s.data && <p>Freshness breaches: {s.data.freshness.breaches.join(", ") || "none"} · open quarantine: {s.data.freshness.quarantine_open}</p>}
      <h3>Dead-letter jobs</h3>
      {jobs.data?.jobs.length === 0 ? <Empty title="No dead-letter jobs." /> : (
        <ul>{jobs.data?.jobs.map((j: any) => <li key={j.id}>{j.kind} · {j.attempts} attempts · <code>{j.last_error}</code>{" "}
          <button className="secondary" onClick={async () => { await api(`/api/v1/admin/jobs/${j.id}/requeue`, { method: "POST" }); jobs.reload(); }}>Requeue</button></li>)}</ul>)}
      <Quarantine />
    </section>
  );
}

export default function Admin() {
  const { can } = useAuth();
  const members = useApi<any>(can("tenant:admin") ? "/api/v1/admin/members" : null);
  const usage = useApi<any>(can("usage:read") ? "/api/v1/admin/usage" : null);
  const audit = useApi<any>(can("audit:read") ? "/api/v1/admin/audit?limit=50" : null);
  const billing = useApi<any>(can("tenant:admin") ? "/api/v1/admin/billing" : null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [msg, setMsg] = useState<string | null>(null);
  if (!can("tenant:admin") && !can("ops:read")) {
    return <><h1>Administration</h1><div className="state restricted">Administration requires the admin role.</div></>;
  }
  return (
    <>
      <h1>Administration</h1>
      {can("tenant:admin") && (
        <>
          <h2>Members</h2>
          {members.data && <DataTable columns={[{ key: "email", label: "Email" }, { key: "role", label: "Role" }]} rows={members.data.members} />}
          <form className="filters" onSubmit={async (e) => { e.preventDefault(); try {
            await api("/api/v1/admin/members", { method: "POST", body: JSON.stringify({ email, role }) }); members.reload(); setMsg("Saved."); }
            catch (err: any) { setMsg(err.message); } }}>
            <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
            <label>Role<select value={role} onChange={(e) => setRole(e.target.value)}>{["viewer", "analyst", "reviewer", "admin"].map((r) => <option key={r}>{r}</option>)}</select></label>
            <button type="submit">Add or change role</button>{msg && <span role="status">{msg}</span>}
          </form>
          <h2>Usage this month</h2>
          {usage.data && <DataTable caption={`Plan: ${usage.data.plan.name}`} columns={[{ key: "m", label: "Metric" }, { key: "used", label: "Used", numeric: true },
            { key: "limit", label: "Limit", numeric: true }]} rows={Object.entries(usage.data.metrics).map(([m, v]: [string, any]) => ({ m, ...v }))} />}
          <h2>Billing</h2>
          {billing.data && <p className="banner warn">{billing.data.detail}</p>}
          <h2>Audit trail</h2>
          {audit.data && <DataTable columns={[{ key: "at", label: "When", format: fmtDate }, { key: "actor", label: "Actor" }, { key: "action", label: "Action" },
            { key: "target_id", label: "Target" }, { key: "outcome", label: "Outcome" }]} rows={audit.data.events} />}
        </>
      )}
      {can("ops:read") && <Ops />}
    </>
  );
}
