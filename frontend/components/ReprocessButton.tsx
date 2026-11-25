"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";

/**
 * Re-run the AI analysis on one call (e.g. after the scoring rules improved). A reviewer's own
 * manual scores are kept: they remember the AI score they were made against.
 */
export default function ReprocessButton({ callId }: { callId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function run() {
    if (!window.confirm("Re-run the AI analysis on this call? The AI scores, summary and compliance flags will be replaced. Manual reviews are kept.")) return;
    setBusy(true);
    setMsg(null);
    try {
      await api.reprocessCall(callId);
      setMsg("Queued. This page will update when it finishes.");
      setTimeout(() => router.refresh(), 4000);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not re-run");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={run}
        disabled={busy}
        className="inline-flex items-center gap-1.5 text-[12px] px-2.5 py-1 rounded-md border border-hairline hover:bg-panelRaised disabled:opacity-50"
      >
        <RefreshCw className={`w-3 h-3 ${busy ? "animate-spin" : ""}`} /> Re-run analysis
      </button>
      {msg && <span className="text-[11.5px] text-muted">{msg}</span>}
    </div>
  );
}
