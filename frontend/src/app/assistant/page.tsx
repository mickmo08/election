"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { useAuth } from "@/lib/auth";
import { ErrorState } from "@/components/States";

export default function Assistant() {
  const { can } = useAuth();
  const history = useApi<any>(can("assistant:query") ? "/api/v1/assistant/history" : null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState<Error | null>(null);
  if (!can("assistant:query")) return <><h1>Research assistant</h1><div className="state restricted">Your role does not include the research assistant.</div></>;
  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<any>("/api/v1/assistant/query", { method: "POST", body: JSON.stringify({ question: q }) });
      setItems([r, ...items]);
      setQ("");
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  }
  const all = [...items, ...(history.data?.queries ?? []).filter((h: any) => !items.some((i) => i.id === h.id))];
  return (
    <>
      <h1>Research assistant</h1>
      <p className="muted">Answers come from read-only platform tools; every number is computed by backend code and cited. The assistant
        does not call races, profile individuals or write persuasion content. AI-assisted — verify before publication.</p>
      <form onSubmit={ask} className="panel">
        <label htmlFor="q">Question</label>
        <textarea id="q" value={q} onChange={(e) => setQ(e.target.value)} maxLength={2000} style={{ minHeight: 80 }}
          placeholder="e.g. What were the 2024 results in NM-03 in the Synthetic Federation?" />
        <p><button type="submit" disabled={busy}>{busy ? "Working…" : "Ask"}</button></p>
      </form>
      {error && <ErrorState error={error} />}
      <div className="chat" aria-live="polite">
        {all.map((r: any) => (
          <article key={r.id} className="panel">
            <div className="msg user">{r.question}</div>
            <div className="msg">
              <span className="badge">{r.status}</span> <span className="badge">AI-assisted</span>
              <p>{r.answer}</p>
              {r.warnings?.length > 0 && <ul className="banner warn">{r.warnings.map((w: string) => <li key={w}>{w}</li>)}</ul>}
              {r.citations?.length > 0 && (
                <details><summary>{r.citations.length} source(s) cited</summary>
                  <ul className="cite">{r.citations.map((c: any) => (
                    <li key={c.id}><strong>[{c.id}]</strong> {c.kind_label}: {c.summary} — {c.source_name ?? "platform computation"}
                      {c.is_synthetic && " (SYNTHETIC)"}{c.stale && " (STALE)"}</li>))}</ul></details>)}
              <p className="muted">Provider {r.provider} · {r.model} · prompt {r.prompt_version} · grounding {r.grounding?.passed === false ? "FAILED" : "passed"}
                {r.fallback_used && " · fallback used"} · {r.latency_ms} ms · query id <code>{r.id}</code></p>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
