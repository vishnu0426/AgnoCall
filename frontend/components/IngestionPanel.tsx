"use client";

import { useState } from "react";
import { IngestionStatus } from "@/lib/api";

function ago(seconds: number | null): string {
  if (seconds == null) return "never";
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

function sinceIso(iso: string | null): string {
  if (!iso) return "no files yet";
  return ago((Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime()) / 1000);
}

const DOT = { healthy: "bg-good", degraded: "bg-warn", down: "bg-bad" } as const;
const TEXT = { healthy: "Receiving recordings", degraded: "Recording intake needs attention", down: "Recording intake is down" } as const;

/**
 * Ingestion status, deliberately quiet: when everything is fine it is just a small
 * dot (click for details). Only a problem adds visible text, since a QA manager
 * needs to know when recordings stop arriving, not that they are arriving.
 */
export default function IngestionPanel({ status }: { status: IngestionStatus | null }) {
  const [open, setOpen] = useState(false);
  if (!status) return null;
  const state = (status.state in DOT ? status.state : "degraded") as keyof typeof DOT;
  const healthy = state === "healthy";

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        title={TEXT[state]}
        aria-label={TEXT[state]}
        className="inline-flex items-center gap-2 text-[12px] px-2 py-1 rounded-md hover:bg-panelRaised"
      >
        <span className={`inline-block w-2 h-2 rounded-full ${DOT[state]}`} />
        {!healthy && <span className={state === "down" ? "text-bad" : "text-warn"}>{TEXT[state]}</span>}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-40 w-80 rounded-lg border border-hairline bg-white shadow-lg p-4 text-[12px]">
          <div className="font-display text-[13px] font-semibold mb-2">{TEXT[state]}</div>
          <dl className="space-y-1 text-muted">
            <Row k="Last recording" v={sinceIso(status.last_ingested_at)} />
            <Row k="Received in last 24h" v={String(status.ingested_last_24h)} />
            <Row k="Waiting to start" v={String(status.pending)} />
            <Row k="Being analysed" v={String(status.processing)} />
            <Row k="Push notification" v={ago(status.webhook_last_seen_seconds_ago)} />
            <Row k="Checked for new files" v={`${ago(status.poller_last_run_seconds_ago)} (every ${status.poll_interval_seconds}s)`} />
          </dl>
          {status.issues.length > 0 && (
            <ul className="mt-3 space-y-1 text-warn list-disc pl-4">
              {status.issues.map((i) => <li key={i}>{i}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-faint">{k}</dt>
      <dd className="text-ink text-right">{v}</dd>
    </div>
  );
}
