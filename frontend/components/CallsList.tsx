"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowDown, ArrowUp, ArrowUpDown, CheckCircle2, PhoneOff, RefreshCw, RotateCcw } from "lucide-react";
import { api, CallSummary, formatCallName, formatDate, formatDuration, riskColor, scoreColor } from "@/lib/api";
import EmptyState from "@/components/EmptyState";
import Badge, { BadgeTone } from "@/components/Badge";

const STATUS_TONE: Record<string, BadgeTone> = {
  uploaded: "muted",
  validating: "warn",
  processing: "accent",
  processed: "good",
  failed: "bad",
};

/** Natural first direction when a column is clicked: worst/lowest first for QA, newest/biggest first otherwise. */
const FIRST_ORDER: Record<string, "asc" | "desc"> = {
  date: "desc", agent: "asc", status: "asc", duration: "desc", qa: "asc", violations: "desc", risk: "desc",
};

const SEVERITY_ORDER = ["critical", "high", "medium", "low"];

function severityText(sev?: Record<string, number>): string {
  if (!sev) return "";
  const keys = [...SEVERITY_ORDER.filter((k) => sev[k]), ...Object.keys(sev).filter((k) => !SEVERITY_ORDER.includes(k))];
  return keys.map((k) => `${sev[k]} ${k}`).join(", ");
}

function worstSeverity(sev?: Record<string, number>): string | null {
  if (!sev) return null;
  return SEVERITY_ORDER.find((k) => sev[k]) ?? null;
}

function qaTitle(c: CallSummary): string | undefined {
  if (c.overall_qa_score == null) return undefined;
  const ai = `AI score ${c.overall_qa_score.toFixed(0)} out of 100`;
  return c.manual_reviewed
    ? `${ai}. A person reviewed this call${c.manual_qa_score != null ? ` and scored it ${c.manual_qa_score.toFixed(0)}` : ""}.`
    : `${ai}. Not yet reviewed by a person.`;
}

function SortHeader({ label, col, sort, order, onSort }: {
  label: string; col: string; sort: string; order: string; onSort: (col: string) => void;
}) {
  const active = sort === col;
  const Icon = !active ? ArrowUpDown : order === "asc" ? ArrowUp : ArrowDown;
  return (
    <th className="px-4 py-2.5 font-medium" aria-sort={active ? (order === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        onClick={() => onSort(col)}
        className={`inline-flex items-center gap-1 uppercase tracking-wider text-[11px] hover:text-ink transition-colors ${active ? "text-ink" : ""}`}
        title={`Sort by ${label.toLowerCase()}`}
      >
        {label}
        <Icon className={`w-3 h-3 ${active ? "" : "opacity-40"}`} />
      </button>
    </th>
  );
}

export default function CallsList({ calls }: { calls: CallSummary[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const sort = searchParams.get("sort") ?? "";
  const order = searchParams.get("order") ?? FIRST_ORDER[sort] ?? "desc";

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  // A new page / filter / sort shows different rows: drop selections that are no longer visible.
  const idsKey = useMemo(() => calls.map((c) => c.id).join(","), [calls]);
  useEffect(() => {
    setSelected((prev) => new Set([...prev].filter((id) => calls.some((c) => c.id === id))));
  }, [idsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  function onSort(col: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (sort === col) {
      params.set("order", order === "asc" ? "desc" : "asc");
    } else {
      params.set("order", FIRST_ORDER[col] ?? "desc");
    }
    params.set("sort", col);
    params.delete("page");
    router.push(`${pathname}?${params.toString()}`);
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const allSelected = calls.length > 0 && calls.every((c) => selected.has(c.id));
  const selectedCalls = calls.filter((c) => selected.has(c.id));
  const selectedFailedRetryable = selectedCalls.filter((c) => c.status === "failed" && c.failure_retryable);

  async function run(label: string, fn: () => Promise<string>) {
    setBusy(label);
    setNotice(null);
    try {
      setNotice({ ok: true, text: await fn() });
      setSelected(new Set());
      router.refresh();
    } catch (e) {
      setNotice({ ok: false, text: e instanceof Error ? e.message : "That did not work. Please try again." });
    } finally {
      setBusy(null);
    }
  }

  const rerun = () =>
    run("rerun", async () => {
      const r = await api.reprocessMany(selectedCalls.map((c) => c.id));
      const parts = [`${r.queued} queued for re-analysis`];
      if (r.busy) parts.push(`${r.busy} still being processed`);
      if (r.cap) parts.push(`${r.cap} already re-run the maximum number of times`);
      return parts.join(" · ");
    });

  const retrySelected = () =>
    run("retry", async () => {
      const r = await api.retryFailed({ call_ids: selectedFailedRetryable.map((c) => c.id) });
      return `${r.retried} queued for retry` + (r.skipped_retry_cap ? ` · ${r.skipped_retry_cap} reached the retry limit` : "");
    });

  const retryOne = (c: CallSummary) =>
    run(`retry-${c.id}`, async () => {
      const r = await api.retryFailed({ call_ids: [c.id] });
      return r.retried ? "Queued for retry." : "This call has reached its retry limit.";
    });

  if (calls.length === 0) {
    return (
      <EmptyState
        icon={PhoneOff}
        title="No calls match"
        description="Try removing a filter, or wait for new recordings to arrive."
      />
    );
  }

  return (
    <div>
      <div className="min-h-[34px] mb-2 flex flex-wrap items-center gap-3" role="status" aria-live="polite">
        {selected.size > 0 ? (
          <>
            <span className="text-[13px] font-medium">{selected.size} selected</span>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => {
                if (window.confirm(`Re-run the analysis for ${selected.size} call${selected.size === 1 ? "" : "s"}? Manual reviews are kept.`)) rerun();
              }}
              className="inline-flex items-center gap-1.5 text-[12.5px] font-medium px-3 py-1.5 rounded-md border border-hairline bg-white hover:border-accent/60 disabled:opacity-50"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Re-run analysis
            </button>
            {selectedFailedRetryable.length > 0 && (
              <button
                type="button"
                disabled={busy !== null}
                onClick={retrySelected}
                className="inline-flex items-center gap-1.5 text-[12.5px] font-medium px-3 py-1.5 rounded-md border border-hairline bg-white hover:border-accent/60 disabled:opacity-50"
              >
                <RotateCcw className="w-3.5 h-3.5" /> Retry {selectedFailedRetryable.length} failed
              </button>
            )}
            <button type="button" onClick={() => setSelected(new Set())} className="text-[12.5px] text-muted hover:text-ink underline">
              Clear selection
            </button>
          </>
        ) : (
          <span className="text-[12.5px] text-faint">Tick calls to re-run analysis or retry failures in bulk.</span>
        )}
        {notice && <span className={`text-[12.5px] ${notice.ok ? "text-good" : "text-bad"}`}>{notice.text}</span>}
      </div>

      <div className="border border-hairline rounded-lg overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-hairline bg-panel text-left text-faint text-[11px] uppercase tracking-wider">
              <th className="pl-4 pr-1 py-2.5 w-8">
                <input
                  type="checkbox"
                  aria-label="Select all calls on this page"
                  checked={allSelected}
                  onChange={() => setSelected(allSelected ? new Set() : new Set(calls.map((c) => c.id)))}
                />
              </th>
              <th className="px-4 py-2.5 font-medium">Call</th>
              <SortHeader label="Date" col="date" sort={sort} order={order} onSort={onSort} />
              <SortHeader label="Agent" col="agent" sort={sort} order={order} onSort={onSort} />
              <SortHeader label="Status" col="status" sort={sort} order={order} onSort={onSort} />
              <SortHeader label="Duration" col="duration" sort={sort} order={order} onSort={onSort} />
              <th className="px-4 py-2.5 font-medium">Processing Time</th>
              <SortHeader label="QA" col="qa" sort={sort} order={order} onSort={onSort} />
              <SortHeader label="Violations" col="violations" sort={sort} order={order} onSort={onSort} />
              <SortHeader label="Risk" col="risk" sort={sort} order={order} onSort={onSort} />
            </tr>
          </thead>
          <tbody>
            {calls.map((call) => {
              const isFailed = call.status === "failed";
              const noSpeech = call.status === "processed" && !call.duration_seconds;
              const worst = worstSeverity(call.violation_severities);
              return (
                <tr
                  key={call.id}
                  className={`border-b border-hairline last:border-0 hover:bg-panel/70 transition-colors ${selected.has(call.id) ? "bg-accent/5" : ""}`}
                >
                  <td className="pl-4 pr-1 py-3 align-top">
                    <input
                      type="checkbox"
                      aria-label={`Select ${call.original_filename}`}
                      checked={selected.has(call.id)}
                      onChange={() => toggle(call.id)}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <Link href={`/calls/${call.id}`} title={call.original_filename} className="text-ink hover:text-accent font-medium">
                      {formatCallName(call.original_filename)}
                    </Link>
                    {isFailed && (
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px]">
                        <span className="text-bad" title={call.failure_advice ?? undefined}>
                          {call.failure_label ?? "Could not be analysed"}
                        </span>
                        {call.failure_retryable ? (
                          <button
                            type="button"
                            disabled={busy !== null}
                            onClick={() => retryOne(call)}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-hairline bg-white hover:border-accent/60 disabled:opacity-50"
                          >
                            <RotateCcw className="w-3 h-3" /> Retry
                          </button>
                        ) : (
                          <span className="text-faint">Retrying will not help</span>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted whitespace-nowrap">{formatDate(call.call_date)}</td>
                  <td className="px-4 py-3 text-muted">{call.agent_name || "—"}</td>
                  <td className="px-4 py-3">
                    <Badge tone={STATUS_TONE[call.status] || "muted"} dot={call.status === "processing"}>
                      {call.status}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 font-mono text-muted tabular">
                    {noSpeech ? (
                      <span className="font-body italic text-faint" title="The recording has no audible speech, so there was nothing to score.">
                        No speech
                      </span>
                    ) : (
                      formatDuration(call.duration_seconds)
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-muted tabular">
                    {call.processing_duration_seconds != null ? `${call.processing_duration_seconds.toFixed(1)}s` : "—"}
                  </td>
                  <td className={`px-4 py-3 font-mono tabular font-medium ${scoreColor(call.overall_qa_score)}`} title={qaTitle(call)}>
                    <span className="inline-flex items-center gap-1.5">
                      {call.overall_qa_score != null ? call.overall_qa_score.toFixed(0) : "—"}
                      {call.manual_reviewed && (
                        <span className="inline-flex items-center gap-0.5 text-good font-body text-[11.5px]">
                          <CheckCircle2 className="w-3.5 h-3.5" aria-hidden />
                          {call.manual_qa_score != null ? call.manual_qa_score.toFixed(0) : "Reviewed"}
                          <span className="sr-only"> reviewed by a person</span>
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono tabular" title={severityText(call.violation_severities) || undefined}>
                    {call.compliance_violation_count > 0 ? (
                      <span className="text-bad">
                        {call.compliance_violation_count}
                        {worst && <span className="font-body text-[11.5px] text-muted ml-1.5">{worst}</span>}
                      </span>
                    ) : (
                      <span className="text-faint">0</span>
                    )}
                  </td>
                  <td className={`px-4 py-3 font-medium ${riskColor(call.risk_level)}`}>{call.risk_level || "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
