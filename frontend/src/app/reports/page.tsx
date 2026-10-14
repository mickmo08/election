"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, fmtDate } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { useAuth } from "@/lib/auth";
import { Empty, ErrorState, Loading } from "@/components/States";

export default function Reports() {
  const { can } = useAuth();
  const router = useRouter();
  const list = useApi<any>("/api/v1/reports");
  const [title, setTitle] = useState("");
  return (
    <>
      <h1>Reports</h1>
      <p className="muted">Drafts are reviewed by someone other than the author before versioned publication. Published versions are
        immutable; corrections create a new version with a correction note.</p>
      {can("reports:write") && (
        <form className="filters" onSubmit={async (e) => {
          e.preventDefault();
          const r = await api<any>("/api/v1/reports", { method: "POST", body: JSON.stringify({ title }) });
          router.push(`/reports/${r.id}`);
        }}>
          <label>New report title<input value={title} onChange={(e) => setTitle(e.target.value)} required minLength={3} /></label>
          <button type="submit">Create draft</button>
        </form>
      )}
      {list.loading && <Loading />}
      {list.error && <ErrorState error={list.error} />}
      {list.data && (list.data.reports.length === 0 ? <Empty title="No reports yet." /> : (
        <div className="table-wrap"><table>
          <thead><tr><th scope="col">Title</th><th scope="col">Status</th><th scope="col" className="num">Versions</th><th scope="col">Created</th></tr></thead>
          <tbody>{list.data.reports.map((r: any) => (
            <tr key={r.id}><th scope="row"><Link href={`/reports/${r.id}`}>{r.title}</Link></th><td><span className="badge">{r.status}</span></td>
              <td className="num">{r.versions}</td><td>{fmtDate(r.created_at)}</td></tr>))}</tbody>
        </table></div>
      ))}
    </>
  );
}
