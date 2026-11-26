import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import { api, ComplianceViolationWithCall, formatCallName, formatDate } from "@/lib/api";
import PageContainer from "@/components/PageContainer";
import MetricCard from "@/components/MetricCard";
import EmptyState from "@/components/EmptyState";
import Badge, { BadgeTone } from "@/components/Badge";
import ComplianceSeverityChart from "@/components/charts/ComplianceSeverityChart";

export const dynamic = "force-dynamic";

const SEVERITY_TONE: Record<string, BadgeTone> = {
  low: "muted",
  medium: "warn",
  high: "bad",
  critical: "bad",
};

const SEVERITY_RANK: Record<string, number> = { low: 0, medium: 1, high: 2, critical: 3 };

/** One row per call (a call with three violations used to fill three rows), newest first, at most 12 calls. */
function groupByCall(violations: ComplianceViolationWithCall[]) {
  const calls = new Map<string, { call_id: string; filename: string; agent: string | null; date: string | null; items: ComplianceViolationWithCall[]; worst: string }>();
  for (const v of violations) {
    const c = calls.get(v.call_id) ?? { call_id: v.call_id, filename: v.call_filename, agent: v.agent_name, date: v.call_date, items: [], worst: "low" };
    if (!c.items.some((x) => x.rule_code === v.rule_code)) c.items.push(v);
    if ((SEVERITY_RANK[v.severity] ?? 0) > (SEVERITY_RANK[c.worst] ?? 0)) c.worst = v.severity;
    calls.set(v.call_id, c);
  }
  return Array.from(calls.values()).slice(0, 12);
}

export default async function CompliancePage() {
  let summary: Awaited<ReturnType<typeof api.complianceSummary>> | null;
  try {
    summary = await api.complianceSummary();
  } catch {
    summary = null;
  }

  const flagged = summary ? groupByCall(summary.recent_violations) : [];
  const topRule = Math.max(1, ...(summary?.by_rule ?? []).map((r) => r.count));
  const totalViolations = (Object.values(summary?.by_severity ?? {}) as number[]).reduce((a, b) => a + b, 0);

  return (
    <PageContainer>
      <header className="mb-7">
        <h1 className="font-display text-[20px] font-semibold tracking-tight">Compliance</h1>
        <p className="text-muted text-[13px] mt-1">
          Which rules are broken most often, and on which calls. Open a call to see each violation with its evidence.
        </p>
      </header>

      {!summary ? (
        <div className="border border-hairline rounded-lg px-5 py-4 text-sm text-warn bg-warn/5">
          Can't reach the API yet — start the backend to see live data.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-3 mb-7">
            <MetricCard label="Processed Calls" value={String(summary.total_processed_calls)} />
            <MetricCard
              label="Clean Call Rate"
              value={summary.clean_call_percent != null ? `${summary.clean_call_percent}%` : "—"}
              accent={summary.clean_call_percent != null && summary.clean_call_percent >= 90 ? "good" : "warn"}
            />
            <MetricCard
              label="Calls With Violations"
              value={String(summary.calls_with_violations)}
              accent={summary.calls_with_violations > 0 ? "bad" : "default"}
            />
          </div>

          {summary.by_rule.length === 0 ? (
            <EmptyState
              variant="good"
              icon={ShieldCheck}
              title="No compliance violations recorded"
              description="Every processed call has come back clean so far."
            />
          ) : (
            <div className="grid lg:grid-cols-[1.4fr_1fr] gap-4 mb-7">
              <section className="border border-hairline rounded-lg bg-panel">
                <div className="px-5 py-3 border-b border-hairline">
                  <h2 className="font-display text-[14px] font-semibold text-ink">Most common violations</h2>
                  <p className="text-[12px] text-muted mt-0.5">How many times each rule was broken, across all processed calls.</p>
                </div>
                <ul className="px-5 py-3 space-y-3">
                  {summary.by_rule.map((r) => (
                    <li key={r.rule_code}>
                      <div className="flex items-baseline justify-between gap-3 text-[13px]">
                        <span className="text-ink font-medium">
                          {r.label}
                          <span className="ml-2 text-[11px] font-normal text-faint">{r.category}</span>
                        </span>
                        <span className="tabular-nums text-muted">{r.count}</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded-full bg-hairline overflow-hidden">
                        <div
                          className="h-full rounded-full bg-accent"
                          style={{ width: `${Math.max(3, (100 * r.count) / topRule)}%` }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
              <section className="border border-hairline rounded-lg bg-panel">
                <div className="px-5 py-3 border-b border-hairline">
                  <h2 className="font-display text-[14px] font-semibold text-ink">By severity</h2>
                  <p className="text-[12px] text-muted mt-0.5">{totalViolations} violations in total.</p>
                </div>
                <div className="px-4 py-3">
                  <ComplianceSeverityChart bySeverity={summary.by_severity} />
                </div>
              </section>
            </div>
          )}

          {flagged.length > 0 && (
            <section>
              <div className="mb-3">
                <h2 className="font-display text-[14px] font-semibold text-ink">Recently flagged calls</h2>
                <p className="text-[12px] text-muted mt-0.5">Newest first. Each call is listed once with everything that was flagged on it.</p>
              </div>
              <div className="border border-hairline rounded-lg overflow-hidden bg-panel">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="border-b border-hairline bg-panelRaised/50 text-left text-faint text-[11px] uppercase tracking-wider">
                      <th className="px-4 py-2.5 font-medium">Call</th>
                      <th className="px-4 py-2.5 font-medium">Agent</th>
                      <th className="px-4 py-2.5 font-medium">What was flagged</th>
                      <th className="px-4 py-2.5 font-medium">Highest</th>
                    </tr>
                  </thead>
                  <tbody>
                    {flagged.map((c) => (
                      <tr key={c.call_id} className="border-b border-hairline last:border-0 hover:bg-panelRaised/60 transition-colors align-top">
                        <td className="px-4 py-3">
                          <Link href={`/calls/${c.call_id}`} className="text-ink hover:text-accent font-medium">
                            {formatCallName(c.filename).replace(/\.[a-zA-Z0-9]+$/, "")}
                          </Link>
                          <div className="text-[12px] text-faint mt-0.5">{formatDate(c.date)}</div>
                        </td>
                        <td className="px-4 py-3 text-muted whitespace-nowrap">{c.agent || "—"}</td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1.5">
                            {c.items.map((v) => (
                              <Badge key={v.id} tone={SEVERITY_TONE[v.severity] || "muted"}>
                                {v.rule_label ?? v.rule_code}
                              </Badge>
                            ))}
                          </div>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <Badge tone={SEVERITY_TONE[c.worst] || "muted"}>{c.worst}</Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </PageContainer>
  );
}
