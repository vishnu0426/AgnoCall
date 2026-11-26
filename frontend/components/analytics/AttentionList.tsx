import Link from "next/link";
import { AttentionItem } from "@/lib/api";

/** The calls to open first, each with the reason it is on the list (not a bare count). */
export default function AttentionList({
  items,
  total,
  allHref,
}: {
  items: AttentionItem[];
  total: number;
  allHref: string;
}) {
  if (items.length === 0) {
    return <div className="py-6 text-center text-[12.5px] text-muted">Nothing needs attention in this period.</div>;
  }
  return (
    <div>
      <ul className="divide-y divide-hairline">
        {items.map((c) => (
          <li key={c.call_id} className="flex items-start gap-4 py-2.5">
            <div className="min-w-0 flex-1">
              <Link
                href={`/calls/${c.call_id}`}
                title={c.filename}
                className="block truncate text-[13px] font-medium text-ink hover:text-accent"
              >
                {c.filename}
              </Link>
              <div className="text-[12px] text-faint">{c.agent ?? "Agent not identified"}</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {c.reasons.map((r) => (
                  <span key={r} className="rounded bg-bad/8 px-1.5 py-0.5 text-[11.5px] text-bad ring-1 ring-inset ring-bad/15">
                    {r}
                  </span>
                ))}
              </div>
            </div>
            <div className="shrink-0 text-right">
              <div className="font-mono text-[15px] tabular text-ink">{c.qa != null ? Math.round(c.qa) : "—"}</div>
              <div className="text-[11px] text-faint">QA</div>
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-2 border-t border-hairline pt-3 text-[12.5px] text-muted">
        Showing the {items.length} most serious of {total} call{total === 1 ? "" : "s"} with at least one reason.{" "}
        <Link href={allHref} className="font-medium text-accent hover:underline">
          See the lowest-scoring calls
        </Link>
      </div>
    </div>
  );
}
