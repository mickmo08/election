"use client";
import { useState } from "react";
import { useApi } from "@/lib/useApi";
import { AboutData, Empty, ErrorState, Loading, SyntheticBanner } from "@/components/States";
import { DataTable, LineChart } from "@/components/Charts";

export default function Issues() {
  const [country, setCountry] = useState("XS");
  const [weeks, setWeeks] = useState(12);
  const t = useApi<any>(`/api/v1/issues/trends?country=${country}&weeks=${weeks}`);
  const ev = useApi<any>("/api/v1/issues/evaluation");
  return (
    <>
      <h1>Public issues</h1>
      <div className="banner warn" role="note">Topic <strong>frequency in covered text</strong> — not public opinion, sentiment,
        support or voting intention. Results depend on which licensed sources are covered.</div>
      <div className="filters">
        <label>Country<select value={country} onChange={(e) => setCountry(e.target.value)}>
          <option value="XS">Synthetic Federation (demo)</option><option value="US">United States</option></select></label>
        <label>Weeks<select value={weeks} onChange={(e) => setWeeks(+e.target.value)}>{[4, 8, 12, 26].map((w) => <option key={w}>{w}</option>)}</select></label>
      </div>
      <SyntheticBanner show={country === "XS"} />
      {t.loading && <Loading />}
      {t.error && <ErrorState error={t.error} />}
      {t.data && (t.data.coverage.documents === 0 ? (
        <Empty title="No covered text for this country and period.">No licensed news or permitted public-discussion source is connected
          (see the source registry). Nothing is inferred in its absence.</Empty>
      ) : (
        <>
          <LineChart title="Share of documents mentioning each topic, by week" xLabel="Week starting" yUnit="%"
            description={`cells with fewer than ${t.data.min_cell} documents are suppressed`}
            series={Object.entries(t.data.series).map(([k, pts]: [string, any]) => ({ name: t.data.labels[k],
              points: pts.map((p: any) => ({ x: p.period, y: p.share === null ? null : +(p.share * 100).toFixed(1) })) }))} />
          <h2>Coverage</h2>
          <DataTable columns={[{ key: "k", label: "Measure" }, { key: "v", label: "Value" }]} rows={[
            { k: "De-duplicated documents", v: t.data.coverage.documents },
            { k: "Syndicated duplicates excluded", v: t.data.coverage.duplicates_excluded },
            { k: "Sources", v: t.data.coverage.sources },
            { k: "Languages", v: Object.entries(t.data.coverage.languages).map(([l, n]) => `${l}: ${n}`).join(", ") },
            { k: "Geographic confidence", v: Object.entries(t.data.coverage.geo_confidence).map(([l, n]) => `${l}: ${n}`).join(", ") },
          ]} />
          <AboutData source="Licensed/permitted text sources (see registry)." period={`Last ${weeks} weeks`}
            metric={`Share of de-duplicated documents in which the topic classifier (${t.data.model_version}, taxonomy ${t.data.taxonomy_version}) detects the topic.`}
            limitations="Lexicon classifier (English/Spanish). Geography comes from source metadata only; documents without it count toward the national total." />
        </>
      ))}
      <h2>Classifier evaluation</h2>
      {ev.data && (
        <>
          <p className="muted">{ev.data.caveat} {ev.data.n_documents} labelled documents · model {ev.data.model_version}</p>
          <DataTable columns={[{ key: "topic", label: "Topic" }, { key: "precision", label: "Precision", numeric: true, format: (v) => v?.toFixed(2) ?? "—" },
            { key: "recall", label: "Recall", numeric: true, format: (v) => v?.toFixed(2) ?? "—" }, { key: "f1", label: "F1", numeric: true, format: (v) => v?.toFixed(2) ?? "—" },
            { key: "support", label: "Positives", numeric: true }]}
            rows={[...Object.entries(ev.data.per_topic).map(([k, v]: [string, any]) => ({ topic: k, ...v })), { topic: "Micro-average", ...ev.data.micro }]} />
        </>
      )}
    </>
  );
}
