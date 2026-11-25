"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Wand2 } from "lucide-react";
import { api } from "@/lib/api";

/** Attach existing agent-less calls to an agent read from the extension in the file name. Safe to repeat. */
export default function DetectAgentsButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.detectAgents();
      setMsg(
        r.assigned === 0
          ? `Nothing new to assign${r.unrecognised ? ` (${r.unrecognised} file names have no recognisable extension)` : ""}.`
          : `Assigned ${r.assigned} call${r.assigned === 1 ? "" : "s"}${r.agents_created ? `, created ${r.agents_created} agent${r.agents_created === 1 ? "" : "s"}` : ""}.`
      );
      router.refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not detect agents");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        onClick={run}
        disabled={busy}
        className="inline-flex items-center gap-1.5 text-[13px] font-medium px-3 py-1.5 rounded-md border border-hairline bg-white hover:bg-panelRaised disabled:opacity-50"
      >
        <Wand2 className="w-3.5 h-3.5" /> {busy ? "Detecting…" : "Detect agents from file names"}
      </button>
      {msg && <span className="text-[11.5px] text-muted max-w-[320px] text-right">{msg}</span>}
    </div>
  );
}
