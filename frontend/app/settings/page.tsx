"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, AppSetting } from "@/lib/api";
import PageContainer from "@/components/PageContainer";

const inputCls =
  "text-[13px] border border-hairline rounded-md px-3 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-accent";

function SettingRow({ s, canEdit, onChanged }: { s: AppSetting; canEdit: boolean; onChanged: (all: AppSetting[]) => void }) {
  const [draft, setDraft] = useState(String(s.value));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setDraft(String(s.value)), [s.value]);

  async function run(fn: () => Promise<AppSetting[]>) {
    setBusy(true);
    setError(null);
    try {
      onChanged(await fn());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  const dirty = s.kind !== "bool" && draft !== String(s.value);
  const rangeText = s.minimum !== null && s.maximum !== null ? `${s.minimum}–${s.maximum}` : "";

  return (
    <div className="px-5 py-4 flex flex-wrap items-start justify-between gap-4 border-t border-hairline first:border-t-0">
      <div className="min-w-0 max-w-xl">
        <div className="text-[13.5px] font-medium">{s.label}</div>
        <div className="text-[12.5px] text-muted mt-0.5">{s.help}</div>
        <div className="text-[11.5px] text-faint mt-1">
          {s.is_default ? "Default" : `Changed${s.updated_by ? ` by ${s.updated_by}` : ""}`}
          {!s.is_default && ` · default is ${String(s.default)}`}
        </div>
        {error && <div className="text-[12.5px] text-bad mt-1">{error}</div>}
      </div>
      <div className="flex items-center gap-2">
        {s.kind === "bool" ? (
          <label className="flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={Boolean(s.value)}
              disabled={!canEdit || busy}
              onChange={(e) => run(() => api.updateSetting(s.key, e.target.checked))}
            />
            {s.value ? "On" : "Off"}
          </label>
        ) : (
          <>
            <input
              type="number"
              value={draft}
              disabled={!canEdit || busy}
              step={s.kind === "int" ? 1 : "any"}
              onChange={(e) => setDraft(e.target.value)}
              className={`${inputCls} w-24 text-right`}
              aria-label={s.label}
            />
            <span className="text-[12px] text-faint w-14">{s.unit}{rangeText && ` (${rangeText})`}</span>
            <button
              disabled={!canEdit || busy || !dirty || draft.trim() === ""}
              onClick={() => run(() => api.updateSetting(s.key, Number(draft)))}
              className="text-[12.5px] font-medium px-3 py-1.5 rounded-md bg-accent text-white hover:opacity-90 disabled:opacity-40"
            >
              Save
            </button>
          </>
        )}
        {!s.is_default && canEdit && (
          <button
            disabled={busy}
            onClick={() => run(() => api.resetSetting(s.key))}
            className="text-[12px] text-muted hover:text-ink underline"
          >
            Reset
          </button>
        )}
      </div>
    </div>
  );
}

function PasswordCard({ signedIn }: { signedIn: boolean }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setMsg({ ok: true, text: "Password changed." });
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : "Could not change password." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bg-white border border-hairline rounded-lg mb-6">
      <div className="px-5 py-3 border-b border-hairline font-display font-semibold text-[14px]">Your password</div>
      {signedIn ? (
        <form onSubmit={submit} className="px-5 py-4 flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="text-[12px] text-faint">Current password</span>
            <input type="password" autoComplete="current-password" value={current}
              onChange={(e) => setCurrent(e.target.value)} className={`${inputCls} block mt-1`} />
          </label>
          <label className="block">
            <span className="text-[12px] text-faint">New password (8+ characters)</span>
            <input type="password" autoComplete="new-password" value={next}
              onChange={(e) => setNext(e.target.value)} className={`${inputCls} block mt-1`} />
          </label>
          <button type="submit" disabled={busy || !current || next.length < 8}
            className="text-[12.5px] font-medium px-3 py-1.5 rounded-md bg-accent text-white hover:opacity-90 disabled:opacity-40">
            Change password
          </button>
          {msg && <span className={`text-[12.5px] ${msg.ok ? "text-good" : "text-bad"}`}>{msg.text}</span>}
        </form>
      ) : (
        <div className="px-5 py-4 text-[13px] text-muted">
          <Link href="/login" className="underline">Sign in</Link> to change your password.
        </div>
      )}
    </section>
  );
}

export default function SettingsPage() {
  const [items, setItems] = useState<AppSetting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [user, setUser] = useState<string | null>(null);

  useEffect(() => {
    try {
      setUser(window.localStorage.getItem("forms_user"));
    } catch {
      setUser(null);
    }
  }, []);

  const load = useCallback(() => {
    api.listSettings().then(setItems).catch((e) => setError(e instanceof Error ? e.message : "Could not load settings."));
  }, []);
  useEffect(load, [load]);

  const groups = items ? Array.from(new Set(items.map((i) => i.group))) : [];

  return (
    <PageContainer>
      <h1 className="font-display text-[22px] font-semibold tracking-tight">Settings</h1>
      <p className="text-[13.5px] text-muted mt-1 mb-6">
        Changes apply immediately, with no restart.{" "}
        {user ? `Signed in as ${user}. Only administrators can change values.` : (
          <>
            <Link href="/login" className="underline">Sign in</Link> as an administrator to change values.
          </>
        )}
      </p>
      {error && <div className="text-[13px] text-bad mb-4">{error}</div>}
      {!items && !error && <div className="text-[13px] text-muted">Loading…</div>}
      {groups.map((g) => (
        <section key={g} className="bg-white border border-hairline rounded-lg mb-6">
          <div className="px-5 py-3 border-b border-hairline font-display font-semibold text-[14px]">{g}</div>
          {items!.filter((i) => i.group === g).map((s) => (
            <SettingRow key={s.key} s={s} canEdit={Boolean(user)} onChanged={setItems} />
          ))}
        </section>
      ))}
      <PasswordCard signedIn={Boolean(user)} />
    </PageContainer>
  );
}
