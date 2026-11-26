import Link from "next/link";
import { BarChart3, Download } from "lucide-react";
import { api, AnalyticsOverview } from "@/lib/api";
import PageContainer from "@/components/PageContainer";
import MetricCard from "@/components/MetricCard";
import EmptyState from "@/components/EmptyState";
import Heatmap from "@/components/charts/Heatmap";
import CategoryTreemap from "@/components/charts/CategoryTreemap";
import TagCloud from "@/components/TagCloud";
import SentimentTrendChart from "@/components/charts/SentimentTrendChart";
import EmotionDistributionChart from "@/components/charts/EmotionDistributionChart";
import QACalibrationCard from "@/components/QACalibrationCard";
import DashboardFilters from "@/components/DashboardFilters";
import DataQualityBanner from "@/components/analytics/DataQualityBanner";

export const dynamic = "force-dynamic";

const ALLOWED_DAYS = new Set([7, 30, 90]);
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOURS = Array.from({ length: 24 }, (_, h) => String(h));
const QA_CRITERIA = [
  "greeting", "identity_verification", "listening", "empathy",
  "communication", "professionalism", "knowledge", "resolution", "closing",
];

function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="bg-panel border border-hairline rounded-lg px-5 py-4">
      <div className="mb-3">
        <div className="text-[11px] uppercase tracking-wide text-faint font-medium">{title}</div>
        {subtitle && <div className="text-[12px] text-muted mt-0.5">{subtitle}</div>}
      </div>
      {children}
    </div>
  );
}

/** "1m 56s" (the card used to show "1:56", which reads as a clock time). */
function minSec(seconds: number | null): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

/** "26 Nov 2026, 15:21 UTC" from the server's ISO time. Fixed format, so it never depends on a locale. */
function updatedAt(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  if (!m) return "";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(m[3])} ${months[Number(m[2]) - 1]} ${m[1]}, ${m[4]}:${m[5]} UTC`;
}

const num = (v: number) => v.toLocaleString("en-US");

function csvCell(v: unknown): string {
  const s = v == null ? "" : String(v);
  // spreadsheet formula injection: a cell that starts with = + - @ would be run as a formula
  const safe = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

function buildCsv(o: AnalyticsOverview, days?: number): string {
  const label: Record<string, string> = {
    processed_calls: "Conversations scored", avg_qa_score: "Avg AI QA", avg_health_score: "Avg health",
    negative_end_percent: "Negative endings (%)", avg_duration_seconds: "Avg duration (s)",
    follow_up_required: "Follow-ups", needs_attention: "Not resolved",
  };
  const rows: unknown[][] = [["Metric", days ? `Last ${days} days` : "All time", days ? `Previous ${days} days` : ""]];
  for (const key of Object.keys(label) as (keyof AnalyticsOverview["kpis"])[]) {
    rows.push([label[key], o.kpis[key], o.kpis_previous ? o.kpis_previous[key] : ""]);
  }
  rows.push(
    [],
    ["Data quality"],
    ["Processed recordings", o.quality.processed],
    ["Real conversations (scored)", o.quality.conversations],
    ["Left out (IVR / silent / very short)", o.quality.excluded],
    ["Scored calls with speech from one side only", o.quality.one_sided],
    ["Scored calls with roles from recording channel", o.quality.roles_from_channel],
    ["Failed recordings", o.quality.failed],
    [],
    ["Generated", o.generated_at],
  );
  return rows.map((r) => r.map(csvCell).join(",")).join("\r\n");
}

export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string; agent_id?: string }>;
}) {
  const sp = await searchParams;
  const parsedDays = Number(sp.days);
  const days = ALLOWED_DAYS.has(parsedDays) ? parsedDays : undefined;
  const agentId = sp.agent_id || undefined;

  const [overviewR, agentsR] = await Promise.allSettled([api.analyticsOverview({ days, agentId }), api.agentOptions()]);
  const overview = overviewR.status === "fulfilled" ? overviewR.value : null;
  const agents = agentsR.status === "fulfilled" ? agentsR.value : [];

  // Every number links to the matching list, keeping the page's own period and agent.
  const scopeParams = new URLSearchParams();
  if (days) scopeParams.set("days", String(days));
  if (agentId) scopeParams.set("agent_id", agentId);
  const scope = scopeParams.toString();
  const callsHref = (extra: string) => `/calls?${[scope, extra].filter(Boolean).join("&")}`;

  const k = overview?.kpis;
  // Only compare when the previous period has data: "up 29" against an empty period says nothing.
  const prev = overview?.kpis_previous && overview.kpis_previous.processed_calls > 0 ? overview.kpis_previous : null;
  const q = overview?.quality;
  const trendLabel = days ? `vs previous ${days} days` : "";
  const sample = k ? `${num(k.processed_calls)} call${k.processed_calls === 1 ? "" : "s"}` : "";
  const rolesPct = q && q.conversations ? Math.round((100 * q.roles_from_channel) / q.conversations) : null;
  const csv = overview ? buildCsv(overview, days) : "";

  return (
    <PageContainer>
      <header className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-[20px] font-semibold tracking-tight">Analytics</h1>
          <p className="text-muted text-[13px] mt-1">
            Patterns across your real conversations: volume, quality, topics, and how AI scoring compares to your
            reviewers.
          </p>
        </div>
        {overview && (
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <a
              href={`data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`}
              download={`analytics-${days ? `${days}d` : "all"}.csv`}
              className="inline-flex items-center gap-1.5 rounded-md border border-hairline bg-white px-3 py-1.5 text-[13px] font-medium hover:border-accent/60"
              title="Download the headline numbers for this period"
            >
              <Download className="h-3.5 w-3.5" /> Export CSV
            </a>
            <span className="text-[11.5px] text-faint">Updated {updatedAt(overview.generated_at)}</span>
          </div>
        )}
      </header>

      <DashboardFilters agents={agents} />

      {!overview || !k || !q ? (
        <div className="border border-hairline rounded-lg px-5 py-4 text-sm text-warn bg-warn/5">
          Can&apos;t reach the API yet — start the backend to see live data.
        </div>
      ) : q.processed === 0 ? (
        <EmptyState
          icon={BarChart3}
          title={days || agentId ? "No processed calls match these filters" : "No processed calls yet"}
          description={
            days || agentId
              ? "Try a longer period or all agents."
              : "Upload recordings and analytics will build up here as they finish processing."
          }
        />
      ) : (
        <>
          <DataQualityBanner quality={q} scope={scope} />

          {q.conversations === 0 ? (
            <EmptyState
              icon={BarChart3}
              title="No real conversations in this selection"
              description={`Every processed recording here is shorter than ${q.min_words} words or ${q.min_seconds} seconds (IVR surveys, silent or very short calls). You can change that limit in Settings.`}
            />
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mb-7">
                <MetricCard
                  label="Conversations scored"
                  value={num(k.processed_calls)}
                  href={callsHref("conversation=true&status=processed")}
                  hint="Processed recordings with enough speech to be a real conversation. Only these are averaged below."
                  trend={prev ? { current: k.processed_calls, previous: prev.processed_calls, higherIsBetter: true } : undefined}
                  trendLabel={trendLabel}
                />
                <MetricCard
                  label="Avg AI QA"
                  value={k.avg_qa_score != null ? String(k.avg_qa_score) : "—"}
                  accent={k.avg_qa_score != null && k.avg_qa_score >= 85 ? "good" : "default"}
                  href={callsHref("conversation=true&sort=qa&order=asc")}
                  hint="Average of the AI's overall QA score (0-100) across the scored conversations."
                  note={`Based on ${sample}`}
                  trend={prev ? { current: k.avg_qa_score, previous: prev.avg_qa_score, higherIsBetter: true, decimals: 1 } : undefined}
                  trendLabel={trendLabel}
                />
                <MetricCard
                  label="Avg health"
                  value={k.avg_health_score != null ? String(k.avg_health_score) : "—"}
                  hint="A 0-100 blend of how the call went: resolution, customer sentiment and agent behaviour. Higher is better."
                  note={`Based on ${sample}`}
                  trend={prev ? { current: k.avg_health_score, previous: prev.avg_health_score, higherIsBetter: true, decimals: 1 } : undefined}
                  trendLabel={trendLabel}
                />
                <MetricCard
                  label="Negative endings"
                  value={k.negative_end_percent != null ? `${k.negative_end_percent}%` : "—"}
                  accent={k.negative_end_percent != null && k.negative_end_percent > 20 ? "bad" : "default"}
                  hint="Share of scored calls where the customer sounded negative at the end of the call. Over 20% shows in red."
                  note={`Based on ${sample}`}
                  trend={prev ? { current: k.negative_end_percent, previous: prev.negative_end_percent, higherIsBetter: false, unit: " pts", decimals: 1 } : undefined}
                  trendLabel={trendLabel}
                />
                <MetricCard
                  label="Avg duration"
                  value={minSec(k.avg_duration_seconds)}
                  hint="Average call length of the scored conversations."
                />
                <MetricCard
                  label="Follow-ups"
                  value={num(k.follow_up_required)}
                  accent={k.follow_up_required > 0 ? "warn" : "default"}
                  hint="Scored calls where the AI found something the team still has to do (a callback, a promised action)."
                  trend={prev ? { current: k.follow_up_required, previous: prev.follow_up_required, higherIsBetter: false } : undefined}
                  trendLabel={trendLabel}
                />
                <MetricCard
                  label="Not resolved"
                  value={num(k.needs_attention)}
                  accent={k.needs_attention > 0 ? "bad" : "good"}
                  sublabel="escalated, unresolved or callback"
                  hint="Scored calls whose outcome was escalated, unresolved or needs a callback. "
                  trend={prev ? { current: k.needs_attention, previous: prev.needs_attention, higherIsBetter: false } : undefined}
                  trendLabel={trendLabel}
                />
                <MetricCard
                  label="Roles confirmed"
                  value={rolesPct != null ? `${rolesPct}%` : "—"}
                  accent={rolesPct != null && rolesPct < 50 ? "warn" : "default"}
                  hint="Share of scored calls where agent and customer were told apart by recording channel (stereo). Mono recordings are a best guess, which affects every agent score."
                />
              </div>

              <div className="space-y-4">
                <div className="grid lg:grid-cols-5 gap-4">
                  <div className="lg:col-span-3">
                    <Card title="Categories" subtitle="Click a tile to open those calls">
                      <CategoryTreemap stats={overview.category_stats} scope={scope} />
                    </Card>
                  </div>
                  <div className="lg:col-span-2">
                    <div className="bg-panel border border-hairline rounded-lg px-5 py-4 h-full flex flex-col">
                      <div className="mb-1">
                        <div className="text-[11px] uppercase tracking-wide text-faint font-medium">Terms &amp; Phrases</div>
                        <div className="text-[12px] text-muted mt-0.5">What customers call about</div>
                      </div>
                      <div className="flex-1 min-h-0 min-h-[260px]">
                        <TagCloud keywords={overview.keywords.slice(0, 28)} />
                      </div>
                      <details className="mt-2 text-[12.5px]">
                        <summary className="cursor-pointer text-muted hover:text-ink">View as a ranked table</summary>
                        <table className="mt-2 w-full text-left">
                          <thead className="text-[11px] uppercase tracking-wide text-faint">
                            <tr>
                              <th className="py-1 font-medium">Term</th>
                              <th className="font-medium">Calls</th>
                              <th className="font-medium">Sentiment</th>
                            </tr>
                          </thead>
                          <tbody>
                            {overview.keywords.slice(0, 15).map((kw) => (
                              <tr key={kw.keyword} className="border-t border-hairline">
                                <td className="py-1.5">{kw.keyword}</td>
                                <td className="tabular">{kw.count}</td>
                                <td>
                                  {kw.avg_sentiment == null
                                    ? "—"
                                    : kw.avg_sentiment > 0.15
                                      ? "positive"
                                      : kw.avg_sentiment < -0.15
                                        ? "negative"
                                        : "neutral"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </details>
                    </div>
                  </div>
                </div>

                <div className="grid lg:grid-cols-2 gap-4">
                  <Card title="Agent × QA Criteria" subtitle="Average AI score per criterion — coaching targets in red">
                    <Heatmap
                      cells={overview.agent_criteria_heatmap}
                      cols={QA_CRITERIA.filter((c) => overview.agent_criteria_heatmap.some((cell) => cell.col === c))}
                      scale="diverging"
                      midpoint={70}
                      max={100}
                      showValues
                    />
                  </Card>
                  <Card title="Call Volume" subtitle="When calls come in — weekday × hour">
                    <Heatmap cells={overview.volume_heatmap} rows={WEEKDAYS} cols={HOURS} scale="sequential" colTickEvery={3} />
                  </Card>
                </div>

                <div className="grid lg:grid-cols-2 gap-4">
                  <Card title="Sentiment Trend" subtitle={`Overall call sentiment per day, last ${days ?? 30} days`}>
                    <SentimentTrendChart trend={overview.sentiment_trend} />
                  </Card>
                  <Card title="Customer Emotions" subtitle="Dominant customer emotion per call">
                    <EmotionDistributionChart distribution={overview.emotion_distribution} />
                  </Card>
                </div>

                <Card title="QA Calibration" subtitle="How AI scoring compares to human reviewers (all reviewed calls)">
                  <QACalibrationCard calibration={overview.qa_calibration} />
                </Card>

                <p className="pt-1 text-[12px] text-faint">
                  Need to change what counts as a real conversation? See{" "}
                  <Link href="/settings" className="text-accent hover:underline">
                    Settings
                  </Link>
                  .
                </p>
              </div>
            </>
          )}
        </>
      )}
    </PageContainer>
  );
}
