import Link from "next/link";
import { ReviewQueue, formatCallName, formatDate } from "@/lib/api";

/** The calls a QA manager should open first, each with the reason it is here. */
export default function ReviewQueuePanel({ queue }: { queue: ReviewQueue | null }) {
  if (!queue) return null;
  return (
    <section className="border border-hairline rounded-lg bg-panel">
      <div className="px-5 py-3 border-b border-hairline flex items-baseline justify-between">
        <h2 className="font-display text-[14px] font-semibold text-ink">Needs review</h2>
        <span className="text-[12px] text-faint">{queue.total} call{queue.total === 1 ? "" : "s"}</span>
      </div>
      {queue.items.length === 0 ? (
        <p className="px-5 py-6 text-[12.5px] text-muted">Nothing urgent. Every flagged call has been reviewed.</p>
      ) : (
        <ul className="divide-y divide-hairline">
          {queue.items.map((i) => (
            <li key={i.call_id}>
              <Link href={`/calls/${i.call_id}`} className="block px-5 py-2.5 hover:bg-panelRaised/60">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[13px] text-ink truncate">{formatCallName(i.filename)}</span>
                  <span className="text-[11.5px] text-faint shrink-0">
                    {i.agent_name ?? "No agent"} · {formatDate(i.call_date)}
                  </span>
                </div>
                <div className="text-[12px] text-warn mt-0.5">{i.reasons.join(" · ")}</div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
