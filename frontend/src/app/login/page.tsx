"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, OIDC_AUTHORITY, oidcManager } from "@/lib/auth";
import { ErrorState } from "@/components/States";

const DEMO = [
  ["demo-admin", "Admin + platform operator"], ["demo-analyst", "Analyst"], ["demo-reviewer", "Reviewer"],
  ["demo-viewer", "Viewer"], ["uni-analyst", "Analyst (second organization)"],
];

export default function Login() {
  const { loginWithToken } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<Error | null>(null);
  const [subject, setSubject] = useState("demo-analyst");

  async function devLogin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await fetch("/api/v1/dev/token", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ subject }) });
      if (!res.ok) throw new Error(res.status === 404 ? "Demo sign-in is disabled in this environment." : `HTTP ${res.status}`);
      const body = await res.json();
      await loginWithToken(body.token, body.tenants[0].slug);
      router.replace("/");
    } catch (err) {
      setError(err as Error);
    }
  }

  return (
    <div className="panel">
      <h1>Sign in</h1>
      {OIDC_AUTHORITY ? (
        <p><button onClick={async () => (await oidcManager()).signinRedirect()}>Sign in with your organization (SSO)</button></p>
      ) : (
        <p className="muted">No OIDC provider is configured for this deployment.</p>
      )}
      <h2>Demo sign-in (development only)</h2>
      <p className="muted">Demo accounts see only the fictional Synthetic Federation dataset and empty U.S. views
        (U.S. sources are not yet connected).</p>
      <form onSubmit={devLogin} className="filters">
        <label>Demo user
          <select value={subject} onChange={(e) => setSubject(e.target.value)}>
            {DEMO.map(([s, l]) => <option key={s} value={s}>{l}</option>)}
          </select>
        </label>
        <button type="submit">Continue</button>
      </form>
      {error && <ErrorState error={error} />}
    </div>
  );
}
