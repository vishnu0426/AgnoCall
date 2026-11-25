import { api } from "@/lib/api";
import MetricCard from "@/components/MetricCard";
import CallsTable from "@/components/CallsTable";
import IngestionPanel from "@/components/IngestionPanel";
import UploadButton from "@/components/UploadButton";
import FailuresPanel from "@/components/FailuresPanel";
import DashboardFilters from "@/components/DashboardFilters";
import QATrendChart from "@/components/QATrendChart";
import ReviewQueuePanel from "@/components/ReviewQueuePanel";
import AIEvaluationCard from "@/components/AIEvaluationCard";
import PageContainer from "@/components/PageContainer";

export const dynamic = "force-dynamic";

const ALLOWED_DAYS = new Set([7, 30, 90]);

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string; agent_id?: string }>;
}) {
  const sp = await searchParams;
  const parsedDays = Number(sp.days);
  const days = ALLOWED_DAYS.has(parsedDays) ? parsedDays : undefined;
  const agentId = sp.agent_id || undefined;

  // Independent requests run in parallel; any one failing must not blank the page.
  const [summaryR, failuresR, ingestionR, queueR, aiR, agentsR] = await Promise.allSettled([
    api.dashboardSummary({ days, agentId }),
    api.failureSummary(),
    api.ingestionStatus(),
    api.reviewQueue({ days, agentId, limit: 6 }),
    api.aiEvaluation(),
    api.agentOptions(),
  ]);
  const ok = <T,>(r: PromiseSettledResult<T>) => (r.status === "fulfilled" ? r.value : null);
  const summary = ok(summaryR);
  const failures = ok(failuresR);
  const ingestion = ok(ingestionR);
  const queue = ok(queueR);
  const ai = ok(aiR);
  const agents = ok(agentsR) ?? [];

  // Cards link to the matching list, keeping the dashboard's own period/agent filter.
  const scope = new URLSearchParams();
  if (days) scope.set("days", String(days));
  if (agentId) scope.set("agent_id", agentId);
  const link = (extra: Record<string, string>) => {
    const p = new URLSearchParams(scope);
    Object.entries(extra).forEach(([k, v]) => p.set(k, v));
    const qs = p.toString();
    return `/calls${qs ? `?${qs}` : ""}`;
  };

  const prev = summary?.previous ?? null;
  const trendLabel = days ? `vs previous ${days} days` : "";
  const qaTarget = summary?.qa_target ?? 80;
  const compTarget = summary?.compliance_target ?? 95;

  return (
    <PageContainer>
      <header className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-[20px] font-semibold tracking-tight">Dashboard</h1>
          <p className="text-muted text-[13px] mt-1">
            Recordings are picked up automatically and analysed as they arrive.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <IngestionPanel status={ingestion} />
          <UploadButton />
        </div>
      </header>

      <DashboardFilters agents={agents} />

      {!summary ? (
        <div className="border border-hairline rounded-lg px-5 py-4 text-sm text-warn bg-warn/5 mb-7">
          Can&apos;t reach the API yet — start the backend to see live data.
        </div>
      ) : (
        <div className="flex flex-wrap gap-3 mb-5">
          <MetricCard
            label="Total Calls"
            value={String(summary.total_calls)}
            href={link({})}
            trend={prev ? { current: summary.total_calls, previous: prev.total_calls, higherIsBetter: true } : undefined}
            trendLabel={trendLabel}
          />
          <MetricCard
            label="Processed"
            value={String(summary.processed)}
            accent="good"
            href={link({ status: "processed" })}
            trend={prev ? { current: summary.processed, previous: prev.processed, higherIsBetter: true } : undefined}
            trendLabel={trendLabel}
          />
          <MetricCard label="Processing" value={String(summary.processing)} href={link({ status: "processing" })} />
          <MetricCard
            label="Failed"
            value={String(summary.failed_actionable)}
            accent={summary.failed_actionable > 0 ? "bad" : "default"}
            sublabel={summary.failed_expected > 0 ? `+${summary.failed_expected} silent` : undefined}
            href={link({ status: "failed" })}
            trend={prev ? { current: summary.failed_actionable, previous: prev.failed_actionable, higherIsBetter: false } : undefined}
            trendLabel={trendLabel}
          />
          <MetricCard
            label="Avg QA Score"
            value={summary.average_qa != null ? summary.average_qa.toFixed(0) : "—"}
            accent={summary.average_qa == null ? "default" : summary.average_qa >= qaTarget ? "good" : "warn"}
            sublabel={`target ${qaTarget}`}
            href="/analytics"
            trend={prev ? { current: summary.average_qa, previous: prev.average_qa, higherIsBetter: true, decimals: 1 } : undefined}
            trendLabel={trendLabel}
          />
          <MetricCard
            label="Compliance"
            value={summary.compliance_percent != null ? `${summary.compliance_percent}%` : "—"}
            accent={summary.compliance_percent == null ? "default" : summary.compliance_percent >= compTarget ? "good" : "warn"}
            sublabel={`target ${compTarget}%`}
            href="/compliance"
            trend={prev ? { current: summary.compliance_percent, previous: prev.compliance_percent, higherIsBetter: true, unit: " pts", decimals: 1 } : undefined}
            trendLabel={trendLabel}
          />
          <MetricCard
            label="High Risk"
            value={String(summary.high_risk_calls)}
            accent={summary.high_risk_calls > 0 ? "bad" : "default"}
            href={link({ risk_level: "high" })}
            trend={prev ? { current: summary.high_risk_calls, previous: prev.high_risk_calls, higherIsBetter: false } : undefined}
            trendLabel={trendLabel}
          />
        </div>
      )}

      <FailuresPanel summary={failures} />

      {summary && (
        <div className="grid gap-4 mb-7 lg:grid-cols-2">
          <section className="border border-hairline rounded-lg bg-panel">
            <div className="px-5 py-3 border-b border-hairline">
              <h2 className="font-display text-[14px] font-semibold text-ink">QA score by day</h2>
            </div>
            <div className="px-4 py-3">
              <QATrendChart points={summary.qa_trend} target={qaTarget} />
            </div>
          </section>
          <ReviewQueuePanel queue={queue} />
        </div>
      )}

      <AIEvaluationCard data={ai} />

      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-display text-[14px] font-semibold text-ink">Recent Calls</h2>
        </div>
        <CallsTable calls={summary?.recent_calls || []} />
      </section>
    </PageContainer>
  );
}
