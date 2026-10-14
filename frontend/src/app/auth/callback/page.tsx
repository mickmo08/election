"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { oidcManager, useAuth } from "@/lib/auth";
import { ErrorState, Loading } from "@/components/States";

export default function Callback() {
  const { loginWithToken } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<Error | null>(null);
  useEffect(() => {
    (async () => {
      const user = await (await oidcManager()).signinRedirectCallback();
      const res = await fetch("/api/v1/my-tenants", { headers: { authorization: `Bearer ${user.access_token}` } });
      if (!res.ok) throw new Error(`Sign-in was not accepted by the platform (HTTP ${res.status}).`);
      const { tenants } = await res.json();
      if (!tenants.length) throw new Error("Your account is not a member of any organization yet. Ask an administrator to add you.");
      await loginWithToken(user.access_token, tenants[0].slug);
      router.replace("/");
    })().catch(setError);
  }, [loginWithToken, router]);
  return error ? <ErrorState error={error} /> : <Loading label="Completing sign-in" />;
}
