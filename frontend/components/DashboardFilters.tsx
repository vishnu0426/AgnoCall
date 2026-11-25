"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AgentOption } from "@/lib/api";

const PERIODS = [
  { value: "", label: "All time" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

const SELECT =
  "text-[13px] border border-hairline rounded-md px-2.5 py-1.5 bg-panel text-ink hover:border-accent/50 focus:outline-none focus:ring-1 focus:ring-accent";

/** Period and agent filters for the whole dashboard. State lives in the URL, so a filtered view can be shared. */
export default function DashboardFilters({ agents }: { agents: AgentOption[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const days = sp.get("days") ?? "";
  const agent = sp.get("agent_id") ?? "";

  function set(key: string, value: string) {
    const params = new URLSearchParams(sp.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    const qs = params.toString();
    router.push(`${pathname}${qs ? `?${qs}` : ""}`);
  }

  return (
    <div className="flex flex-wrap items-center gap-2 mb-5">
      <select aria-label="Period" className={SELECT} value={days} onChange={(e) => set("days", e.target.value)}>
        {PERIODS.map((p) => (
          <option key={p.value} value={p.value}>{p.label}</option>
        ))}
      </select>
      <select aria-label="Agent" className={SELECT} value={agent} onChange={(e) => set("agent_id", e.target.value)}>
        <option value="">All agents</option>
        {agents.map((a) => (
          <option key={a.id} value={a.id}>{a.name}</option>
        ))}
      </select>
      {(days || agent) && (
        <button onClick={() => router.push(pathname)} className="text-[13px] text-muted hover:text-ink px-2 py-1.5">
          Clear
        </button>
      )}
    </div>
  );
}
