"use client";
import { use } from "react";
import Link from "next/link";
import { useApi } from "@/lib/useApi";
import { fmtDate, fmtInt, fmtPct } from "@/lib/api";
import { AboutData, ErrorState, Loading, StatusBadge, SyntheticBanner } from "@/components/States";
import { BarChart, DataTable } from "@/components/Charts";
import { PARTY_COLORS } from "@/components/Picker";

export default function ContestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: c, error, loading, reload } = useApi<any>(`/api/v1/contests/${id}`);
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!c) return null;
  const cur = c.current;
  const outcome = c.implied_outcome;
  return (
    <>
      <p><Link href="/explorer">← Explorer</Link></p>
      <h1>{c.name}</h1>
      <SyntheticBanner show={c.is_synthetic} />
      <p className="muted">{c.office.name} · {c.election.kind} election on {fmtDate(c.election.date)} · system: {c.electoral_system}
        {c.seats > 1 ? ` · ${c.seats} seats` : ""}{c.is_special ? " · special election" : ""}
        {c.district && <> · district {c.district.code} ({c.district.plan}, boundaries: {c.district.boundary_status})</>}</p>
      {c.district && <p><Link href={`/history?district=${c.district.id}`}>Compare this district across cycles →</Link></p>}
      {!cur ? (
        <div className="state empty">No results have been published for this contest by a registered source.</div>
      ) : (
        <>
          <div className="panel">
            <StatusBadge status={cur.status} /> <strong>{cur.status_label}</strong>
            {cur.disputed && <div className="banner warn">Disputed: {cur.dispute_note}</div>}
            {cur.correction_note && <div className="banner warn">Correction: {cur.correction_note}</div>}
            <div className="muted">
              Source: {cur.source?.name} ({cur.source?.publisher}) · source timestamp {fmtDate(cur.source_as_of)} · retrieved {fmtDate(cur.retrieved_at)}
              {" · "}{cur.reporting_supported ? `${cur.reporting_pct}% reporting (as reported by source)` : "reporting completeness not provided by source"}
              {cur.turnout && ` · turnout ${cur.turnout.pct}% of ${cur.turnout.denominator} voters`}
            </div>
          </div>
          <BarChart title="Vote share" description={`${cur.status} count`} unit="%"
            rows={cur.lines.map((l: any) => ({ label: l.label + (l.party ? ` (${l.party})` : ""), share: l.share, color: PARTY_COLORS[l.party] }))}
            labelKey="label" valueKey="share" colorKey="color" />
          <DataTable caption="Reported count" columns={[
            { key: "label", label: "Candidate / line" }, { key: "party", label: "Party" },
            { key: "votes", label: "Votes", numeric: true, format: fmtInt }, { key: "share", label: "Share", numeric: true, format: (v) => fmtPct(v, 2) }]}
            rows={cur.lines} />
          <div className="panel">
            <h2>Outcome</h2>
            {c.race_calls.length > 0 ? (
              <p>Race call ({c.race_calls.at(-1).status}) by <strong>{c.race_calls.at(-1).caller}</strong> at {fmtDate(c.race_calls.at(-1).called_at)}:{" "}
                {c.race_calls.at(-1).candidate}. <span className="muted">{c.race_calls.at(-1).note}</span></p>
            ) : (
              <p><strong>No race call recorded.</strong> Calls are shown only from sources authorized by the editorial policy; the
                platform never calls races automatically.</p>
            )}
            {outcome && <p className="muted">What the reported count implies under {c.electoral_system} (not a call):{" "}
              {outcome.kind === "plurality_leader" && `${outcome.leader} leads by ${fmtInt(outcome.margin_votes)} votes.`}
              {outcome.kind === "runoff_required" && `no majority; a runoff between ${outcome.advancing.join(" and ")} would be required.`}
              {outcome.kind === "rcv_tabulation_required" && outcome.note}
              {outcome.kind === "advancing" && `advancing: ${outcome.advancing.join(", ")}.`}
              {outcome.kind === "seat_allocation" && `D'Hondt allocation: ${Object.entries(outcome.seats).map(([k, v]) => `${k} ${v}`).join(", ")}.`}</p>}
          </div>
        </>
      )}
      <h2>Snapshot history</h2>
      <DataTable caption="Every published snapshot is preserved; corrections reference what they supersede." columns={[
        { key: "retrieved_at", label: "Retrieved", format: fmtDate }, { key: "status", label: "Status" },
        { key: "source_as_of", label: "Source timestamp", format: fmtDate },
        { key: "reporting_pct", label: "Reporting", numeric: true, format: (v) => (v === null ? "n/a" : `${v}%`) },
        { key: "total_votes", label: "Total votes", numeric: true, format: fmtInt },
        { key: "correction_note", label: "Correction note" }]} rows={c.history} />
      <h2>Candidates</h2>
      <DataTable columns={[{ key: "name", label: "Ballot name" }, { key: "party", label: "Party" },
        { key: "incumbent", label: "Incumbent", format: (v) => (v === null ? "unknown" : v ? "yes" : "no") }, { key: "status", label: "Status" }]}
        rows={c.candidates} />
      <AboutData source={<>Contest from <code>{c.provenance.contest_source}</code>; results from the snapshot source shown above.</>}
        period={`${c.election.cycle} ${c.election.kind}`} metric="Votes and shares as published; shares computed over all listed lines."
        limitations="Preliminary and unofficial counts change. Candidacy status reflects the loading source (e.g. an FEC filing is not ballot qualification)." />
    </>
  );
}
