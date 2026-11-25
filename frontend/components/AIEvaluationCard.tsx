import Link from "next/link";
import { AIEvaluationSummary } from "@/lib/api";

/** How the AI-scored forms are doing, and how often the AI agrees with a human who scored the same call. */
export default function AIEvaluationCard({ data }: { data: AIEvaluationSummary | null }) {
  if (!data || data.enabled_forms === 0) return null;
  return (
    <section className="border border-hairline rounded-lg bg-panel mb-7">
      <div className="px-5 py-3 border-b border-hairline flex items-baseline justify-between">
        <h2 className="font-display text-[14px] font-semibold text-ink">AI evaluation</h2>
        <Link href="/forms" className="text-[12px] text-accent hover:underline">Manage forms</Link>
      </div>
      <ul className="divide-y divide-hairline">
        {data.items.map((f) => (
          <li key={f.form_id} className="px-5 py-3 flex flex-wrap items-center justify-between gap-x-8 gap-y-1">
            <div className="text-[13px] text-ink">
              {f.title} <span className="text-faint text-[11.5px]">v{f.version}</span>
            </div>
            <dl className="flex gap-6 text-[12px] text-muted">
              <div><dt className="inline text-faint">Calls scored </dt><dd className="inline text-ink font-mono">{f.scored_calls}</dd></div>
              <div>
                <dt className="inline text-faint">Average </dt>
                <dd className="inline text-ink font-mono">
                  {f.average_score != null ? `${f.average_score} / ${f.total_score}` : "—"}
                </dd>
              </div>
              <div>
                <dt className="inline text-faint">Agrees with reviewers </dt>
                <dd className="inline text-ink font-mono">
                  {f.agreement_percent != null ? `${f.agreement_percent}% (${f.compared_with_human})` : "no human scores yet"}
                </dd>
              </div>
            </dl>
          </li>
        ))}
      </ul>
    </section>
  );
}
