"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";
import { FailureSummary, api } from "@/lib/api";

/**
 * One calm line until the manager asks for more. Only failures that need attention
 * are listed; silent recordings (not a fault) are tucked behind a link. Each group
 * explains itself in plain English with the raw technical text under "Details".
 * Only retryable groups get a Retry button; the server enforces that and a per-call cap.
 */
export default function FailuresPanel({ summary }: { summary: FailureSummary | null }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [showSilent, setShowSilent] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  if (!summary || summary.total_failed === 0) return null;

  const actionable = summary.groups.filter((g) => !g.expected);
  const silent = summary.groups.filter((g) => g.expected);

  async function retry(category?: string) {
    setBusy(category ?? "all");
    setMessage(null);
    try {
      const r = await api.retryFailed({ category });
      setMessage(
        r.retried > 0
          ? `Re-queued ${r.retried} call${r.retried === 1 ? "" : "s"}.${r.skipped_retry_cap ? ` ${r.skipped_retry_cap} reached the retry limit.` : ""}`
          : "Nothing to retry."
      );
      router.refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Retry failed");
    } finally {
      setBusy(null);
    }
  }

  // Nothing needs attention: don't take any space.
  if (summary.actionable === 0 && !showSilent) {
    return (
      <p className="text-[12px] text-faint mb-5">
        {summary.expected} silent recording{summary.expected === 1 ? "" : "s"} skipped (nothing to analyse).
      </p>
    );
  }

  return (
    <section className="mb-5 rounded-lg border border-warn/30 bg-warn/5">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-2 text-[13px] text-ink text-left"
          aria-expanded={open}
        >
          <AlertTriangle className="w-4 h-4 text-warn shrink-0" />
          <span>
            <span className="font-medium">{summary.actionable} call{summary.actionable === 1 ? "" : "s"} could not be analysed</span>
            {summary.retryable > 0 && <span className="text-muted"> · {summary.retryable} can be retried</span>}
          </span>
          {open ? <ChevronUp className="w-3.5 h-3.5 text-faint" /> : <ChevronDown className="w-3.5 h-3.5 text-faint" />}
        </button>
        {summary.retryable > 0 && (
          <button
            onClick={() => retry()}
            disabled={busy !== null}
            className="text-[12.5px] font-medium px-3 py-1 rounded-md border border-hairline bg-white hover:bg-panelRaised disabled:opacity-50"
          >
            {busy === "all" ? "Retrying…" : "Retry all"}
          </button>
        )}
      </div>

      {open && (
        <div className="border-t border-warn/20 bg-white rounded-b-lg">
          <ul className="divide-y divide-hairline">
            {actionable.map((g) => (
              <li key={g.category} className="px-4 py-3 flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 max-w-[760px]">
                  <div className="text-[13px] text-ink">
                    <span className="font-mono tabular mr-2">{g.count}</span>
                    {g.label}
                  </div>
                  {g.advice && <div className="text-[12px] text-muted mt-0.5">{g.advice}</div>}
                  {g.sample_reason && (
                    <details className="mt-1">
                      <summary className="text-[11.5px] text-faint cursor-pointer">Details</summary>
                      <div className="text-[11.5px] text-faint break-words mt-1 font-mono">{g.sample_reason}</div>
                    </details>
                  )}
                </div>
                {g.retryable && (
                  <button
                    onClick={() => retry(g.category)}
                    disabled={busy !== null}
                    className="text-[12px] px-2.5 py-1 rounded-md border border-hairline hover:bg-panelRaised disabled:opacity-50"
                  >
                    {busy === g.category ? "Retrying…" : "Retry"}
                  </button>
                )}
              </li>
            ))}
          </ul>
          {silent.length > 0 && (
            <div className="px-4 py-2.5 border-t border-hairline text-[12px] text-faint">
              {summary.expected} silent recording{summary.expected === 1 ? "" : "s"} are not counted
              {" — "}
              <button className="underline" onClick={() => setShowSilent((s) => !s)}>
                {showSilent ? "hide" : "what are these?"}
              </button>
              {showSilent && <div className="mt-1 text-muted">{silent[0].advice}</div>}
            </div>
          )}
          {message && <div className="px-4 py-2 text-[12px] text-muted border-t border-hairline">{message}</div>}
        </div>
      )}
    </section>
  );
}
