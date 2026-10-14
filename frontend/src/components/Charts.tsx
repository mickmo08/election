"use client";
/* Accessible SVG charts. Each chart is a <figure> with a caption and an always-available data table. */
import { useId, useState } from "react";

const PALETTE = ["#2563eb", "#dc2626", "#0f766e", "#c2410c", "#7c3aed", "#ca8a04", "#475569", "#db2777"];

export type Column = { key: string; label: string; format?: (v: any) => string; numeric?: boolean };

export function DataTable({ columns, rows, caption }: { columns: Column[]; rows: any[]; caption?: string }) {
  return (
    <div className="table-wrap">
      <table>
        {caption && <caption>{caption}</caption>}
        <thead>
          <tr>{columns.map((c) => <th key={c.key} scope="col" className={c.numeric ? "num" : undefined}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c, j) => {
                const v = c.format ? c.format(r[c.key]) : r[c.key] ?? "—";
                return j === 0 ? <th key={c.key} scope="row">{v}</th> :
                  <td key={c.key} className={c.numeric ? "num" : undefined}>{v}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TableToggle({ children, defaultOpen = false }: { children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div>
      <button className="link" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        {open ? "Hide" : "Show"} data table
      </button>
      <div id={id} hidden={!open}>{children}</div>
    </div>
  );
}

export function BarChart({ title, rows, valueKey, labelKey, unit = "", colorKey, description }: {
  title: string; rows: any[]; valueKey: string; labelKey: string; unit?: string; colorKey?: string; description?: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r[valueKey] ?? 0));
  const bar = 26;
  const height = rows.length * (bar + 8);
  return (
    <figure className="chart">
      <figcaption><strong>{title}</strong>{description && <span className="muted"> — {description}</span>}</figcaption>
      <svg role="img" aria-label={`${title}. ${rows.map((r) => `${r[labelKey]}: ${r[valueKey]}${unit}`).join("; ")}`}
        viewBox={`0 0 600 ${height}`} width="100%" preserveAspectRatio="xMinYMin meet">
        {rows.map((r, i) => {
          const w = ((r[valueKey] ?? 0) / max) * 380;
          return (
            <g key={i} transform={`translate(0, ${i * (bar + 8)})`}>
              <text x={0} y={bar / 2 + 5} className="axis-label">{String(r[labelKey]).slice(0, 24)}</text>
              <rect x={190} width={Math.max(w, 1)} height={bar} rx={3}
                fill={(colorKey && r[colorKey]) || PALETTE[i % PALETTE.length]} />
              <text x={196 + w} y={bar / 2 + 5} className="value-label">{r[valueKey]}{unit}</text>
            </g>
          );
        })}
      </svg>
      <TableToggle>
        <DataTable columns={[{ key: labelKey, label: "Item" }, { key: valueKey, label: `Value${unit ? ` (${unit})` : ""}`, numeric: true }]} rows={rows} />
      </TableToggle>
    </figure>
  );
}

export function LineChart({ title, series, xLabel, yUnit = "", description, colors = {} }: {
  title: string; series: { name: string; points: { x: string; y: number | null }[] }[]; xLabel: string; yUnit?: string;
  description?: string; colors?: Record<string, string>;
}) {
  const color = (name: string, i: number) => colors[name] ?? PALETTE[i % PALETTE.length];
  const xs = Array.from(new Set(series.flatMap((s) => s.points.map((p) => p.x)))).sort();
  const ys = series.flatMap((s) => s.points.map((p) => p.y)).filter((v): v is number => v !== null);
  const [lo, hi] = ys.length ? [Math.min(...ys, 0), Math.max(...ys)] : [0, 1];
  const W = 640, H = 260, L = 48, B = 30;
  const sx = (x: string) => L + (xs.length > 1 ? (xs.indexOf(x) / (xs.length - 1)) * (W - L - 10) : 0);
  const sy = (y: number) => H - B - ((y - lo) / (hi - lo || 1)) * (H - B - 10);
  const rows = xs.map((x) => Object.fromEntries([["x", x], ...series.map((s) => [s.name, s.points.find((p) => p.x === x)?.y ?? null])]));
  return (
    <figure className="chart">
      <figcaption><strong>{title}</strong>{description && <span className="muted"> — {description}</span>}</figcaption>
      <svg role="img" aria-label={`${title}. Line chart of ${series.map((s) => s.name).join(", ")} by ${xLabel}. See data table.`}
        viewBox={`0 0 ${W} ${H}`} width="100%">
        {[lo, (lo + hi) / 2, hi].map((t, i) => (
          <g key={i}><line x1={L} x2={W} y1={sy(t)} y2={sy(t)} className="gridline" />
            <text x={4} y={sy(t) + 4} className="axis-label">{t.toFixed(1)}{yUnit}</text></g>
        ))}
        {xs.length > 0 && [xs[0], xs[xs.length - 1]].map((x, i) => (
          <text key={i} x={sx(x)} y={H - 8} textAnchor={i ? "end" : "start"} className="axis-label">{x}</text>
        ))}
        {series.map((s, i) => {
          const pts = s.points.filter((p) => p.y !== null);
          return (
            <g key={s.name}>
              <polyline fill="none" stroke={color(s.name, i)} strokeWidth={2.5}
                strokeDasharray={i % 2 ? "6 3" : undefined}
                points={pts.map((p) => `${sx(p.x)},${sy(p.y as number)}`).join(" ")} />
              {pts.map((p) => <circle key={p.x} cx={sx(p.x)} cy={sy(p.y as number)} r={3} fill={color(s.name, i)} />)}
            </g>
          );
        })}
      </svg>
      <ul className="legend">{series.map((s, i) => (
        <li key={s.name}><span className="swatch" style={{ background: color(s.name, i) }} />{s.name}</li>))}
      </ul>
      <TableToggle>
        <DataTable columns={[{ key: "x", label: xLabel }, ...series.map((s) => ({ key: s.name, label: s.name, numeric: true,
          format: (v: number | null) => (v === null || v === undefined ? "suppressed / n.a." : `${v}${yUnit}`) }))]} rows={rows} />
      </TableToggle>
    </figure>
  );
}
