"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";
import { Loading } from "./States";

const NAV = [
  ["/", "Election overview"], ["/explorer", "Contests & districts"], ["/results", "Results monitoring"],
  ["/history", "Historical comparison"], ["/issues", "Public issues"], ["/polls", "Polling & surveys"],
  ["/forecasts", "Forecasts & methodology"], ["/assistant", "Research assistant"], ["/reports", "Reports"],
  ["/sources", "Source registry"], ["/admin", "Administration"],
] as const;

export function Shell({ children }: { children: React.ReactNode }) {
  const { session, me, ready, logout, switchTenant } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const open = pathname === "/login" || pathname.startsWith("/auth/");
  useEffect(() => {
    if (ready && !session && !open) router.replace("/login");
  }, [ready, session, open, router]);
  if (open) return <main id="main" className="main narrow">{children}</main>;
  if (!ready || !session || !me) return <main id="main" className="main"><Loading label="Signing in" /></main>;
  return (
    <div className="layout">
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <span className="brand">Election Intelligence</span>
        <label className="tenant">
          <span className="sr-only">Organization</span>
          <select value={me.tenant} onChange={(e) => switchTenant(e.target.value)}>
            {me.tenants.map((t) => <option key={t.slug} value={t.slug}>{t.name}</option>)}
          </select>
        </label>
        <span className="muted">{me.user} · {me.role}{me.is_operator ? " · platform operator" : ""}</span>
        {me.environment !== "production" && <span className="badge env">{me.environment}</span>}
        <button className="link" onClick={logout}>Sign out</button>
      </header>
      <nav aria-label="Primary" className="sidenav">
        <ul>
          {NAV.map(([href, label]) => (
            <li key={href}>
              <Link href={href} aria-current={(href === "/" ? pathname === "/" : pathname.startsWith(href)) ? "page" : undefined}>
                {label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <main id="main" className="main" tabIndex={-1}>{children}</main>
    </div>
  );
}
