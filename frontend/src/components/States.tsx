"use client";
import { ApiError } from "@/lib/api";

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" /> {label}…
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="state empty" role="status">
      <strong>{title}</strong>
      {children && <div>{children}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  if (error instanceof ApiError && error.status === 403) {
    return (
      <div className="state restricted" role="alert">
        <strong>Restricted.</strong> Your role does not include access to this view.
        <div className="muted">{String(error.detail)}</div>
      </div>
    );
  }
  if (error instanceof ApiError && error.status === 401) {
    return <div className="state restricted" role="alert"><strong>Signed out.</strong> <a href="/login">Sign in again</a>.</div>;
  }
  const rid = error instanceof ApiError ? error.requestId : null;
  return (
    <div className="state error" role="alert">
      <strong>Something went wrong.</strong> {error instanceof ApiError ? `HTTP ${error.status}: ` : ""}
      {error.message}
      {rid && <div className="muted">Request ID: <code>{rid}</code> (quote this to support)</div>}
      {onRetry && <button onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function SyntheticBanner({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div className="banner synthetic" role="note">
      <strong>SYNTHETIC DEMO DATA.</strong> This view shows the fictional “Synthetic Federation”. Nothing here is real
      election data.
    </div>
  );
}

export function Freshness({ f }: { f?: { state: string; age_hours: number | null; sla_hours: number | null } | null }) {
  if (!f) return null;
  const label: Record<string, string> = {
    fresh: "Fresh", stale: "STALE", never_loaded: "Never loaded", unavailable: "Unavailable", no_sla: "No refresh SLA",
  };
  return (
    <span className={`badge fresh-${f.state}`} title={f.age_hours !== null ? `${f.age_hours} h since last success` : undefined}>
      {label[f.state] ?? f.state}
      {f.state === "stale" && f.sla_hours ? ` (SLA ${f.sla_hours} h)` : ""}
    </span>
  );
}

/** Every analytical view states its source, period and metric. */
export function AboutData({ source, period, metric, limitations }: {
  source: React.ReactNode; period: React.ReactNode; metric: React.ReactNode; limitations?: React.ReactNode;
}) {
  return (
    <aside className="about" aria-label="About this data">
      <dl>
        <dt>Source</dt><dd>{source}</dd>
        <dt>Period</dt><dd>{period}</dd>
        <dt>Metric</dt><dd>{metric}</dd>
        {limitations && (<><dt>Limitations</dt><dd>{limitations}</dd></>)}
      </dl>
    </aside>
  );
}

export function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="badge">No results</span>;
  return <span className={`badge status-${status}`}>{status}</span>;
}
