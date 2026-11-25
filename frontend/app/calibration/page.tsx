import Link from "next/link";
import { api, CalibrationSummary, SampleCall, formatCallName } from "@/lib/api";
import PageContainer from "@/components/PageContainer";

export const dynamic = "force-dynamic";

const VERDICT_STYLE: Record<CalibrationSummary["verdict_level"], string> = {
  not_enough_data: "border-hairline bg-panel text-muted",
  about_right: "border-good/30 bg-good/5 text-good",
  harsh: "border-warn/40 bg-warn/5 text-warn",
  generous: "border-warn/40 bg-warn/5 text-warn",
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bg-panel border border-hairline rounded-lg px-5 py-4 flex-1 min-w-[160px]">
      <div className="text-[11px] uppercase tracking-wider text-faint font-medium mb-2">{label}</div>
      <div className="font-mono text-[24px] leading-none font-medium tabular text-ink">{value}</div>
      {hint && <div className="text-[12px] text-muted mt-1.5">{hint}</div>}
    </div>
  );
}

function biasWords(bias: number | null): string {
  if (bias == null) return "—";
  if (Math.abs(bias) < 5) return "about right";
  return bias > 0 ? `${bias.toFixed(0)} pts too harsh` : `${Math.abs(bias).toFixed(0)} pts too generous`;
}

export default async function CalibrationPage() {
  let s: CalibrationSummary | null = null;
  let sample: SampleCall[] = [];
  const [sr, pr] = await Promise.allSettled([api.calibrationSummary(), api.calibrationSample(15)]);
  if (sr.status === "fulfilled") s = sr.value;
  if (pr.status === "fulfilled") sample = pr.value;

  if (!s) {
    return (
      <PageContainer>
        <h1 className="font-display text-[20px] font-semibold tracking-tight">Calibration</h1>
        <p className="text-warn text-[13px] mt-3">Can&apos;t reach the API yet.</p>
      </PageContainer>
    );
  }

  const progress = Math.min(100, Math.round((100 * s.reviewed_calls) / s.target_reviews));
  const nearlyAllFlagged = s.flagged_call_percent != null && s.flagged_call_percent >= 90;

  return (
    <PageContainer>
      <header className="mb-6">
        <h1 className="font-display text-[20px] font-semibold tracking-tight">Calibration</h1>
        <p className="text-muted text-[13px] mt-1">
          Is the AI marking in line with your reviewers? Score a sample of calls by hand and the app compares the two.
        </p>
      </header>

      <div className={`rounded-lg border px-5 py-4 mb-5 ${VERDICT_STYLE[s.verdict_level]}`}>
        <div className="text-[14px] font-medium">{s.verdict_text}</div>
        <div className="mt-3">
          <div className="flex justify-between text-[11.5px] text-muted mb-1">
            <span>Calls reviewed by a person</span>
            <span className="font-mono">{s.reviewed_calls} / {s.target_reviews}</span>
          </div>
          <div className="h-1.5 rounded bg-hairline overflow-hidden">
            <div className="h-full bg-accent" style={{ width: `${progress}%` }} />
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 mb-5">
        <Stat label="AI average" value={s.ai_average_qa != null ? s.ai_average_qa.toFixed(0) : "—"} hint="across all processed calls" />
        <Stat label="Reviewers' average" value={s.human_average_qa != null ? s.human_average_qa.toFixed(0) : "—"} hint="on the calls they scored" />
        <Stat label="Agreement" value={s.agreement_percent != null ? `${s.agreement_percent}%` : "—"} hint="AI within 10 points of a person" />
        <Stat label="Typical gap" value={s.mean_abs_error != null ? `${s.mean_abs_error} pts` : "—"} hint={biasWords(s.bias)} />
      </div>

      {nearlyAllFlagged && (
        <div className="rounded-lg border border-warn/40 bg-warn/5 px-5 py-3 mb-5 text-[13px] text-ink">
          <span className="font-medium">{s.flagged_call_percent}% of processed calls have at least one compliance flag.</span>{" "}
          That is rarely realistic and usually means the AI is flagging too eagerly. Mark the flags below as
          &ldquo;Correct&rdquo; or &ldquo;Wrong&rdquo; on each call&apos;s Compliance tab to measure it.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <section className="border border-hairline rounded-lg bg-panel">
          <div className="px-5 py-3 border-b border-hairline">
            <h2 className="font-display text-[14px] font-semibold">Where the AI is off (by criterion)</h2>
          </div>
          {s.by_criterion.length === 0 ? (
            <p className="px-5 py-6 text-[12.5px] text-muted">Complete a Manual QA review on a few calls to see this.</p>
          ) : (
            <table className="w-full text-[12.5px]">
              <thead>
                <tr className="text-left text-faint text-[11px] uppercase tracking-wider border-b border-hairline">
                  <th className="px-5 py-2 font-medium">Criterion</th>
                  <th className="px-2 py-2 font-medium">AI is</th>
                  <th className="px-2 py-2 font-medium">Agrees</th>
                  <th className="px-5 py-2 font-medium text-right">Calls</th>
                </tr>
              </thead>
              <tbody>
                {s.by_criterion.map((c) => (
                  <tr key={c.criterion} className="border-b border-hairline last:border-0">
                    <td className="px-5 py-2 capitalize">{c.criterion.replace(/_/g, " ")}</td>
                    <td className="px-2 py-2 text-muted">{biasWords(c.bias)}</td>
                    <td className="px-2 py-2 font-mono tabular">{c.agreement_percent != null ? `${c.agreement_percent}%` : "—"}</td>
                    <td className="px-5 py-2 font-mono tabular text-right text-muted">{c.n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="border border-hairline rounded-lg bg-panel">
          <div className="px-5 py-3 border-b border-hairline flex items-baseline justify-between">
            <h2 className="font-display text-[14px] font-semibold">Are the compliance flags right?</h2>
            <span className="text-[12px] text-faint">{s.compliance.unreviewed_flags} not yet checked</span>
          </div>
          {s.compliance.reviewed === 0 ? (
            <p className="px-5 py-6 text-[12.5px] text-muted">
              Open a call&apos;s Compliance tab and mark each flag Correct or Wrong. The share you uphold is the AI&apos;s precision.
            </p>
          ) : (
            <>
              <div className="px-5 py-3 text-[13px]">
                <span className="font-mono text-[20px]">{s.compliance.precision_percent}%</span>{" "}
                <span className="text-muted">of checked flags were right ({s.compliance.confirmed} of {s.compliance.reviewed})</span>
              </div>
              <table className="w-full text-[12.5px]">
                <tbody>
                  {s.compliance.by_rule.map((r) => (
                    <tr key={r.rule_code} className="border-t border-hairline">
                      <td className="px-5 py-2 font-mono text-[12px]">{r.rule_code}</td>
                      <td className="px-2 py-2 text-muted">{r.confirmed} right · {r.rejected} wrong</td>
                      <td className="px-5 py-2 font-mono tabular text-right">{r.precision_percent != null ? `${r.precision_percent}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      </div>

      <section className="border border-hairline rounded-lg bg-panel mb-6">
        <div className="px-5 py-3 border-b border-hairline">
          <h2 className="font-display text-[14px] font-semibold">Calls to score next</h2>
          <p className="text-[12px] text-muted mt-0.5">
            Picked to cover the AI&apos;s whole range (low, middle, high) so a harsh or generous AI can&apos;t hide. Open one, then use the QA Scorecard tab&apos;s Manual review.
          </p>
        </div>
        {sample.length === 0 ? (
          <p className="px-5 py-6 text-[12.5px] text-muted">No unreviewed processed calls left.</p>
        ) : (
          <ul className="divide-y divide-hairline">
            {sample.map((c) => (
              <li key={c.call_id}>
                <Link href={`/calls/${c.call_id}`} className="flex items-baseline justify-between gap-3 px-5 py-2.5 hover:bg-panelRaised/60">
                  <span className="text-[13px] text-ink truncate">{formatCallName(c.filename)}</span>
                  <span className="text-[12px] text-faint shrink-0">
                    {c.agent_name ?? "No agent"} · AI {c.ai_qa != null ? c.ai_qa.toFixed(0) : "—"} · {c.reason}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="text-[12px] text-faint">
        Scoring rules version <span className="font-mono">{s.rubric_version}</span>.{" "}
        {s.reviewed_calls > 0
          ? `${s.reviewed_on_current_rubric} of ${s.reviewed_calls} reviewed calls were analysed with the current rules. `
          : ""}
        Calls analysed before this version keep their old scores until you use &ldquo;Re-run analysis&rdquo; on them.
      </p>
    </PageContainer>
  );
}
