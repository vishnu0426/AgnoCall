"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, FileText, Loader2, Mail, Pencil, Pause, Play, Plus, Send, Table2, Trash2 } from "lucide-react";
import { api, ReportSchedule, ReportScheduleInput, ReportSchedulesResponse } from "@/lib/api";

const inputCls =
  "text-[13px] border border-hairline rounded-md px-3 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-accent disabled:bg-panelRaised";
const btn = "inline-flex items-center gap-1.5 rounded-md border border-hairline bg-white px-2.5 py-1.5 text-[12.5px] font-medium hover:border-accent/60 disabled:opacity-40";
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const PERIODS = [
  { value: 7, label: "Last 7 days" },
  { value: 30, label: "Last 30 days" },
  { value: 90, label: "Last 90 days" },
  { value: 0, label: "All time" },
];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const BLANK: ReportScheduleInput = {
  name: "", recipients: [], frequency: "weekly", weekday: 0, month_day: null, send_time: "08:00",
  period_days: 7, formats: ["pdf", "csv"], enabled: true,
};

/** "30 Nov 2026, 08:00" from the server's ISO time (already on the report clock). Fixed format, no locale. */
function when(iso: string | null): string {
  const m = iso && /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}, ${m[4]}:${m[5]} UTC` : "—";
}

function ScheduleForm({
  initial, maxRecipients, busy, error, onSave, onCancel,
}: {
  initial: ReportScheduleInput; maxRecipients: number; busy: boolean; error: string | null;
  onSave: (v: ReportScheduleInput) => void; onCancel: () => void;
}) {
  const [v, setV] = useState(initial);
  const [recipients, setRecipients] = useState(initial.recipients.join(", "));
  const set = <K extends keyof ReportScheduleInput>(k: K, val: ReportScheduleInput[K]) => setV((p) => ({ ...p, [k]: val }));
  const toggle = (f: "pdf" | "csv") =>
    set("formats", v.formats.includes(f) ? v.formats.filter((x) => x !== f) : [...v.formats, f]);

  const build = (): ReportScheduleInput => ({
    ...v,
    recipients: recipients.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean),
    weekday: v.frequency === "weekly" ? v.weekday ?? 0 : null,
    month_day: v.frequency === "monthly" ? v.month_day ?? 1 : null,
  });

  const [testing, setTesting] = useState(false);
  const [testNote, setTestNote] = useState<{ ok: boolean; text: string } | null>(null);
  async function sendTest() {
    setTesting(true);
    setTestNote(null);
    try {
      const r = await api.sendReportTest(build());
      setTestNote({ ok: true, text: `Test sent to ${r.sent_to.join(", ")}. Check the inbox, then save the schedule.` });
    } catch (e) {
      setTestNote({ ok: false, text: e instanceof Error ? e.message : "Could not send the test." });
    } finally {
      setTesting(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    onSave(build());
  }

  const label = "block text-[12px] text-faint mb-1";
  return (
    <form onSubmit={submit} className="px-5 py-4 bg-panelRaised/60 border-t border-hairline space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className={label}>Report name</span>
          <input className={`${inputCls} w-full`} value={v.name} maxLength={80} placeholder="Weekly QA summary"
            onChange={(e) => set("name", e.target.value)} />
        </label>
        <label className="block">
          <span className={label}>Recipients (comma or space separated, up to {maxRecipients})</span>
          <input className={`${inputCls} w-full`} value={recipients} placeholder="manager@company.com, qa-lead@company.com"
            onChange={(e) => setRecipients(e.target.value)} />
        </label>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <label className="block">
          <span className={label}>Repeat</span>
          <select className={inputCls} value={v.frequency}
            onChange={(e) => set("frequency", e.target.value as ReportScheduleInput["frequency"])}>
            <option value="daily">Every day</option>
            <option value="weekly">Every week</option>
            <option value="monthly">Every month</option>
          </select>
        </label>
        {v.frequency === "weekly" && (
          <label className="block">
            <span className={label}>On</span>
            <select className={inputCls} value={v.weekday ?? 0} onChange={(e) => set("weekday", Number(e.target.value))}>
              {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
            </select>
          </label>
        )}
        {v.frequency === "monthly" && (
          <label className="block">
            <span className={label}>Day of month (1-28)</span>
            <input type="number" min={1} max={28} className={`${inputCls} w-24`} value={v.month_day ?? 1}
              onChange={(e) => set("month_day", Number(e.target.value))} />
          </label>
        )}
        <label className="block">
          <span className={label}>At</span>
          <input type="time" className={inputCls} value={v.send_time} onChange={(e) => set("send_time", e.target.value)} />
        </label>
        <label className="block">
          <span className={label}>Covers</span>
          <select className={inputCls} value={v.period_days} onChange={(e) => set("period_days", Number(e.target.value))}>
            {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </label>
        <fieldset>
          <legend className={label}>Attach</legend>
          <div className="flex gap-4 py-1.5 text-[13px]">
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={v.formats.includes("pdf")} onChange={() => toggle("pdf")} /> PDF</label>
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={v.formats.includes("csv")} onChange={() => toggle("csv")} /> CSV</label>
          </div>
        </fieldset>
      </div>

      {error && <div role="alert" className="text-[12.5px] text-bad">{error}</div>}
      <div className="flex items-center gap-2">
        <button type="submit" disabled={busy} className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12.5px] font-medium text-white hover:opacity-90 disabled:opacity-40">
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save schedule
        </button>
        <button type="button" disabled={busy || testing} onClick={sendTest}
          title="Email this report to the recipients right now as a test. Nothing is saved."
          className="inline-flex items-center gap-1.5 rounded-md border border-hairline bg-white px-3 py-1.5 text-[12.5px] font-medium hover:bg-panelRaised disabled:opacity-40">
          {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />} Send now
        </button>
        <button type="button" onClick={onCancel} className="px-2 py-1.5 text-[12.5px] text-muted hover:text-ink">Cancel</button>
      </div>
      {testNote && (
        <div role="status" className={`text-[12.5px] ${testNote.ok ? "text-good" : "text-bad"}`}>{testNote.text}</div>
      )}
    </form>
  );
}

export default function ReportSchedules({ signedIn }: { signedIn: boolean }) {
  const [data, setData] = useState<ReportSchedulesResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);      // "new" or a schedule id
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);            // "form" or a schedule id
  const [note, setNote] = useState<{ id: string; ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    if (!signedIn) return;
    api.listReportSchedules().then((d) => { setData(d); setLoadError(null); })
      .catch((e) => setLoadError(e instanceof Error ? e.message : "Could not load scheduled reports."));
  }, [signedIn]);
  useEffect(load, [load]);

  async function save(id: string, body: ReportScheduleInput) {
    setBusy("form");
    setFormError(null);
    try {
      if (id === "new") await api.createReportSchedule(body);
      else await api.updateReportSchedule(id, body);
      setEditing(null);
      load();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setBusy(null);
    }
  }

  async function act(s: ReportSchedule, fn: () => Promise<unknown>, okText?: string) {
    setBusy(s.id);
    setNote(null);
    try {
      await fn();
      if (okText) setNote({ id: s.id, ok: true, text: okText });
    } catch (e) {
      setNote({ id: s.id, ok: false, text: e instanceof Error ? e.message : "Something went wrong." });
    } finally {
      setBusy(null);
      load();
    }
  }

  const asInput = (s: ReportSchedule): ReportScheduleInput => ({
    name: s.name, recipients: s.recipients, frequency: s.frequency, weekday: s.weekday, month_day: s.month_day,
    send_time: s.send_time, period_days: s.period_days, formats: s.formats, enabled: s.enabled,
  });

  return (
    <section className="bg-white border border-hairline rounded-lg mb-6" aria-labelledby="reports-heading">
      <div className="px-5 py-3 border-b border-hairline flex items-center justify-between gap-3">
        <h2 id="reports-heading" className="font-display font-semibold text-[14px]">Scheduled reports</h2>
        {signedIn && data && editing === null && (
          <button onClick={() => { setFormError(null); setEditing("new"); }} className={btn}>
            <Plus className="h-3.5 w-3.5" /> New schedule
          </button>
        )}
      </div>

      {!signedIn ? (
        <div className="px-5 py-4 text-[13px] text-muted">
          <Link href="/login" className="underline">Sign in</Link> as an administrator to schedule reports.
        </div>
      ) : loadError ? (
        <div className="px-5 py-4 text-[13px] text-bad">{loadError}</div>
      ) : !data ? (
        <div className="px-5 py-4 text-[13px] text-muted">Loading…</div>
      ) : (
        <>
          <div className="px-5 py-3 text-[12.5px] border-b border-hairline">
            {data.smtp.configured ? (
              <p className="flex items-start gap-2 text-muted">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-good" />
                <span>
                  Reports are emailed from <b className="text-ink">{data.smtp.from}</b>.
                  Times are in <b className="text-ink">{data.timezone}</b>.
                </span>
              </p>
            ) : (
              <p className="flex items-start gap-2 text-warn">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  Email is not set up, so nothing will be sent. Add <code className="font-mono">SMTP_HOST</code> and{" "}
                  <code className="font-mono">SMTP_FROM</code> (plus <code className="font-mono">SMTP_USERNAME</code> and{" "}
                  <code className="font-mono">SMTP_PASSWORD</code> if your server needs them) to the backend <code className="font-mono">.env</code>,
                  then restart the API and the worker. You can still prepare schedules now.
                </span>
              </p>
            )}
          </div>

          {data.items.length === 0 && editing !== "new" && (
            <div className="px-5 py-6 text-[13px] text-muted">
              No scheduled reports yet. A schedule emails the Analytics numbers as a PDF, a CSV, or both, on the
              days and time you choose.
            </div>
          )}

          {data.items.map((s) =>
            editing === s.id ? (
              <ScheduleForm key={s.id} initial={asInput(s)} maxRecipients={data.max_recipients}
                busy={busy === "form"} error={formError} onSave={(b) => save(s.id, b)} onCancel={() => setEditing(null)} />
            ) : (
              <div key={s.id} className="px-5 py-4 border-t border-hairline first:border-t-0">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-[13.5px] font-medium">
                      <Mail className="h-4 w-4 text-faint" /> {s.name}
                      {!s.enabled && <span className="rounded bg-panelRaised px-1.5 py-0.5 text-[11px] font-normal text-muted">Paused</span>}
                    </div>
                    <div className="mt-1 text-[12.5px] text-muted">
                      {s.when} · {PERIODS.find((p) => p.value === s.period_days)?.label ?? ""} ·{" "}
                      {s.formats.map((f) => (
                        <span key={f} className="mr-1 inline-flex items-center gap-1">
                          {f === "pdf" ? <FileText className="h-3 w-3" /> : <Table2 className="h-3 w-3" />}{f.toUpperCase()}
                        </span>
                      ))}
                    </div>
                    <div className="mt-0.5 text-[12.5px] text-faint" title={s.recipients.join(", ")}>
                      To {s.recipients.slice(0, 3).join(", ")}{s.recipients.length > 3 ? ` and ${s.recipients.length - 3} more` : ""}
                    </div>
                    <div className="mt-1 text-[12px] text-faint">
                      {s.enabled ? `Next: ${when(s.next_run_at)}` : "Not scheduled while paused"}
                      {s.last_run_at && (
                        <> · Last {s.last_status === "sent" ? "sent" : "attempt"}: {when(s.last_run_at)}</>
                      )}
                    </div>
                    {s.last_status === "failed" && s.last_error && (
                      <div className="mt-1 text-[12.5px] text-bad">Last attempt failed: {s.last_error}</div>
                    )}
                    {note?.id === s.id && (
                      <div role="status" className={`mt-1 text-[12.5px] ${note.ok ? "text-good" : "text-bad"}`}>{note.text}</div>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button className={btn} disabled={busy === s.id}
                      onClick={() => act(s, () => api.sendReportNow(s.id), "Sent. Check the recipients' inboxes.")}
                      title="Send this report right now (does not change the schedule)">
                      {busy === s.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />} Send now
                    </button>
                    <button className={btn} disabled={busy === s.id} onClick={() => { setFormError(null); setEditing(s.id); }}>
                      <Pencil className="h-3.5 w-3.5" /> Edit
                    </button>
                    <button className={btn} disabled={busy === s.id}
                      onClick={() => act(s, () => api.updateReportSchedule(s.id, { ...asInput(s), enabled: !s.enabled }))}>
                      {s.enabled ? <><Pause className="h-3.5 w-3.5" /> Pause</> : <><Play className="h-3.5 w-3.5" /> Resume</>}
                    </button>
                    <button className={`${btn} text-bad`} disabled={busy === s.id} aria-label={`Delete ${s.name}`}
                      onClick={() => { if (window.confirm(`Delete the scheduled report "${s.name}"?`)) act(s, () => api.deleteReportSchedule(s.id)); }}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            ),
          )}

          {editing === "new" && (
            <ScheduleForm initial={BLANK} maxRecipients={data.max_recipients} busy={busy === "form"} error={formError}
              onSave={(b) => save("new", b)} onCancel={() => setEditing(null)} />
          )}
        </>
      )}
    </section>
  );
}
