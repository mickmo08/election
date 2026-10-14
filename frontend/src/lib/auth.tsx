"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, setSession, type Session } from "./api";

type Me = { user: string; tenant: string; role: string; is_operator: boolean; permissions: string[];
  tenants: { slug: string; name: string; role: string }[]; environment: string };

type Ctx = {
  session: Session | null;
  me: Me | null;
  ready: boolean;
  can: (perm: string) => boolean;
  loginWithToken: (token: string, tenant: string) => Promise<void>;
  switchTenant: (tenant: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<Ctx>(null as unknown as Ctx);
const KEY = "election.session";
export const OIDC_AUTHORITY = process.env.NEXT_PUBLIC_OIDC_AUTHORITY;
export const OIDC_CLIENT_ID = process.env.NEXT_PUBLIC_OIDC_CLIENT_ID;

export async function oidcManager() {
  const { UserManager, WebStorageStateStore } = await import("oidc-client-ts");
  return new UserManager({
    authority: OIDC_AUTHORITY!,
    client_id: OIDC_CLIENT_ID!,
    redirect_uri: `${window.location.origin}/auth/callback`,
    response_type: "code", // Authorization Code + PKCE
    scope: "openid profile email",
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setS] = useState<Session | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  const establish = useCallback(async (s: Session) => {
    setSession(s);
    const m = await api<Me>("/api/v1/me");
    sessionStorage.setItem(KEY, JSON.stringify(s));
    setS(s);
    setMe(m);
  }, []);

  useEffect(() => {
    const raw = typeof window !== "undefined" ? sessionStorage.getItem(KEY) : null;
    if (raw) {
      establish(JSON.parse(raw))
        .catch(() => sessionStorage.removeItem(KEY))
        .finally(() => setReady(true));
    } else setReady(true);
  }, [establish]);

  const value = useMemo<Ctx>(() => ({
    session, me, ready,
    can: (perm) => !!me?.permissions.includes(perm),
    loginWithToken: (token, tenant) => establish({ token, tenant }),
    switchTenant: async (tenant) => {
      if (session) await establish({ token: session.token, tenant });
    },
    logout: () => {
      sessionStorage.removeItem(KEY);
      setSession(null);
      setS(null);
      setMe(null);
      window.location.href = "/login";
    },
  }), [session, me, ready, establish]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
