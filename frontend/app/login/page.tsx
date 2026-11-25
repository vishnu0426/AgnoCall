"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { API_BASE } from "@/lib/api";
import PageContainer from "@/components/PageContainer";

/**
 * Sign in with the Forms account (POST /auth/login). The token is stored in this browser and sent
 * with GraphQL requests so the server can tell who is enabling or running AI evaluation.
 */
export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      if (!res.ok) {
        throw new Error(res.status === 401 ? "Wrong username or password." : `Sign-in failed (${res.status}).`);
      }
      const data = await res.json();
      window.localStorage.setItem("forms_jwt", data.token);
      window.localStorage.setItem("forms_user", data.user?.username ?? username.trim());
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageContainer>
      <div className="max-w-sm mx-auto mt-16">
        <h1 className="font-display text-[20px] font-semibold tracking-tight mb-1">Sign in</h1>
        <p className="text-[13px] text-muted mb-6">Administrators can enable and run AI evaluation on forms.</p>
        <form onSubmit={submit} className="space-y-3">
          <label className="block">
            <span className="text-[12px] text-faint">Username</span>
            <input
              autoFocus
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="mt-1 w-full text-[13px] border border-hairline rounded-md px-3 py-2 bg-white focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </label>
          <label className="block">
            <span className="text-[12px] text-faint">Password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full text-[13px] border border-hairline rounded-md px-3 py-2 bg-white focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </label>
          {error && <div className="text-[12.5px] text-bad">{error}</div>}
          <button
            type="submit"
            disabled={busy || !username.trim() || !password}
            className="w-full text-[13px] font-medium px-3 py-2 rounded-md bg-accent text-white hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </PageContainer>
  );
}
