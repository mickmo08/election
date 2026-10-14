"use client";

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown, public requestId: string | null) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
}

export type Session = { token: string; tenant: string };

let current: Session | null = null;
export function setSession(s: Session | null) {
  current = s;
}

export async function api<T = any>(path: string, init: RequestInit & { raw?: boolean } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (current) {
    headers.set("authorization", `Bearer ${current.token}`);
    headers.set("x-tenant", current.tenant);
  }
  if (init.body && !(init.body instanceof FormData) && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  const res = await fetch(path, { ...init, headers, cache: "no-store" });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail, res.headers.get("x-request-id"));
  }
  if (init.raw) return res as unknown as T;
  return res.json();
}

export function fmtInt(n: number | null | undefined) {
  return n === null || n === undefined ? "—" : n.toLocaleString("en-US");
}
export function fmtPct(n: number | null | undefined, digits = 1) {
  return n === null || n === undefined ? "—" : `${n.toFixed(digits)}%`;
}
export function fmtDate(s: string | null | undefined) {
  if (!s) return "—";
  const d = new Date(s);
  return isNaN(d.getTime()) ? s : d.toLocaleString("en-US", { dateStyle: "medium", timeStyle: s.length > 10 ? "short" : undefined });
}
