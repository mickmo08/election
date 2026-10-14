"use client";
import { use, useState } from "react";
import Link from "next/link";
import { api, fmtDate } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { useAuth } from "@/lib/auth";
import { ErrorState, Loading } from "@/components/States";

export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useAuth();
  const r = useApi<any>(`/api/v1/reports/${id}`);
  const sources = useApi<any>("/api/v1/sources");
  const history = useApi<any>(can("assistant:query") ? "/api/v1/assistant/history" : null);
  const [form, setForm] = useState({ body_markdown: "", methodology: "", uncertainty: "", correction_note: "" });
  const [srcKeys, setSrcKeys] = useState<string[]>([]);
  const [aiIds, setAiIds] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  if (r.loading) return <Loading />;
  if (r.error) return <ErrorState error={r.error} />;
  const rep = r.data;
  const latest = rep.versions.at(-1);
  const act = async (path: string, body?: object) => {
    setMsg(null);
    try {
      await api(`/api/v1/reports/${id}/${path}`, { method: "POST", body: body ? JSON.stringify(body) : undefined });
      r.reload();
    } catch (e: any) {
      setMsg(typeof e.detail === "object" ? `${e.detail.message}: ${(e.detail.blockers ?? []).join("; ")}` : e.message);
    }
  };
  const download = async (format: string) => {
    const res = await api<Response>(`/api/v1/reports/${id}/export?format=${format}`, { raw: true });
    const url = URL.createObjectURL(await res.blob());
    Object.assign(document.createElement("a"), { href: url, download: `report-${id}.${format}` }).click();
  };
  return (
    <>
      <p><Link href="/reports">← Reports</Link></p>
      <h1>{rep.title}</h1>
      <p><span className="badge">{rep.status}</span> {rep.published_version && <>· published version {rep.published_version}</>}</p>
      {latest && (
        <article className="panel">
          <h2>Version {latest.version} {latest.published_at ? `(published ${fmtDate(latest.published_at)})` : "(draft)"}</h2>
          {latest.ai_assisted && <p className="badge">AI-assisted</p>} {latest.contains_synthetic_data && <p className="banner synthetic">Cites SYNTHETIC data — cannot be published.</p>}
          {latest.correction_note && <p className="banner warn">Correction to v{latest.correction_of_version}: {latest.correction_note}</p>}
          <pre style={{ whiteSpace: "pre-wrap" }}>{latest.body_markdown}</pre>
          <h3>Methodology</h3><p>{latest.methodology}</p>
          <h3>Uncertainty</h3><p>{latest.uncertainty}</p>
          <h3>Sources</h3><ul>{latest.sources.map((s: any) => <li key={s.key}>{s.name} — {s.publisher} ({s.license})</li>)}</ul>
          <p className="muted">Reproducibility: app {latest.reproducibility.app_version} · generated {fmtDate(latest.reproducibility.generated_at)}
            · {latest.reproducibility.assistant_queries.length} assistant queries</p>
          {latest.review_decision && <p>Review: <strong>{latest.review_decision}</strong> — {latest.review_comment}</p>}
          <p>{["md", "html", "json"].map((f) => <button key={f} className="secondary" onClick={() => download(f)}>Download .{f}</button>)}</p>
        </article>
      )}
      {msg && <div className="state error" role="alert">{msg}</div>}
      <div className="filters">
        {can("reports:write") && ["draft", "published"].includes(rep.status) && latest && !latest.published_at &&
          <button onClick={() => act("submit")}>Submit for review</button>}
        {can("reports:publish") && rep.status === "approved" && <button onClick={() => act("publish")}>Publish</button>}
      </div>
      {can("reports:review") && rep.status === "in_review" && (
        <div className="panel"><label>Review comment<input value={comment} onChange={(e) => setComment(e.target.value)} /></label>
          <p><button onClick={() => act("review", { approve: true, comment })} disabled={!comment}>Approve</button>{" "}
            <button className="secondary" onClick={() => act("review", { approve: false, comment })} disabled={!comment}>Request changes</button></p></div>
      )}
      {can("reports:write") && ["draft", "changes_requested", "published"].includes(rep.status) && (
        <form className="panel" onSubmit={(e) => { e.preventDefault(); act("versions", { ...form, correction_note: form.correction_note || null,
          source_keys: srcKeys, ai_query_ids: aiIds, countries: [] }); }}>
          <h2>{rep.status === "published" ? "Issue a correction (new version)" : "New version"}</h2>
          <label>Body (Markdown)<textarea value={form.body_markdown} onChange={(e) => setForm({ ...form, body_markdown: e.target.value })} required /></label>
          <label>Methodology<input value={form.methodology} onChange={(e) => setForm({ ...form, methodology: e.target.value })} required /></label>
          <label>Uncertainty<input value={form.uncertainty} onChange={(e) => setForm({ ...form, uncertainty: e.target.value })} required /></label>
          {rep.status === "published" && <label>Correction note<input value={form.correction_note} onChange={(e) => setForm({ ...form, correction_note: e.target.value })} required /></label>}
          <fieldset><legend>Sources</legend>{sources.data?.sources.map((s: any) => (
            <label key={s.key} style={{ flexDirection: "row" }}><input type="checkbox" checked={srcKeys.includes(s.key)}
              onChange={(e) => setSrcKeys(e.target.checked ? [...srcKeys, s.key] : srcKeys.filter((k) => k !== s.key))} /> {s.name}</label>))}</fieldset>
          {history.data?.queries.length > 0 && <fieldset><legend>Assistant answers used (marks the version AI-assisted)</legend>
            {history.data.queries.slice(0, 10).map((q: any) => (
              <label key={q.id} style={{ flexDirection: "row" }}><input type="checkbox" checked={aiIds.includes(q.id)}
                onChange={(e) => setAiIds(e.target.checked ? [...aiIds, q.id] : aiIds.filter((k) => k !== q.id))} /> {q.question}</label>))}</fieldset>}
          <p><button type="submit">Save version</button></p>
        </form>
      )}
      <h2>Version history</h2>
      <ul>{rep.versions.map((v: any) => <li key={v.version}>v{v.version} · {fmtDate(v.created_at)} · {v.review_decision ?? "not reviewed"}
        {v.published_at && ` · published ${fmtDate(v.published_at)}`}{v.correction_note && ` · correction: ${v.correction_note}`}</li>)}</ul>
    </>
  );
}
