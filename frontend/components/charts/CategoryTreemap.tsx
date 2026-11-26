"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ResponsiveContainer, Treemap, Tooltip } from "recharts";
import { CategoryStat } from "@/lib/api";

/**
 * "Discover Trends"-style categories panel: one tile per call category,
 * sized by call volume, colored by average call sentiment (red = customers
 * leave unhappy, green = happy, gray = neutral/unknown). Labels are drawn
 * only where they fit; the tooltip always carries the full numbers.
 */

const DIV_LOW = "#C1352E";
const DIV_MID = "#E4E7ED";
const DIV_HIGH = "#12805A";

function hexLerp(a: string, b: string, t: number): string {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return "#" + pa.map((v, i) => Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

function sentimentFill(avg: number | null): string {
  if (avg == null) return DIV_MID;
  const t = Math.max(-1, Math.min(1, avg));
  return t < 0 ? hexLerp(DIV_MID, DIV_LOW, -t) : hexLerp(DIV_MID, DIV_HIGH, t);
}

function labelColor(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  return 0.299 * r + 0.587 * g + 0.114 * b > 0.6 ? "#171B24" : "#FFFFFF";
}

function Cell(props: any) {
  const { x, y, width, height, name, count, avg_sentiment, categoryKey, depth, index, onOpen } = props;
  // recharts also draws the root node; only real categories are tiles
  if (width <= 0 || height <= 0 || name == null || !depth) return null;
  const clipId = `tile-${index}-${Math.round(x)}-${Math.round(y)}`;
  const fill = sentimentFill(avg_sentiment ?? null);
  const ink = labelColor(fill);
  const showName = width > 74 && height > 34;
  const showCount = width > 74 && height > 54;
  return (
    <g
      role="link"
      tabIndex={0}
      aria-label={`${name}: ${count} call${count === 1 ? "" : "s"}. Open the list.`}
      style={{ cursor: "pointer", outline: "none" }}
      onClick={() => onOpen?.(categoryKey)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onOpen?.(categoryKey)}
    >
      <clipPath id={clipId}><rect x={x} y={y} width={width} height={height} /></clipPath>
      {/* 2px white stroke = the surface gap between adjacent tiles */}
      <rect x={x} y={y} width={width} height={height} rx={3} fill={fill} stroke="#FFFFFF" strokeWidth={2} />
      {showName && (
        <text x={x + 9} y={y + 20} fontSize={12} fontWeight={500} fill={ink} clipPath={`url(#${clipId})`}
          style={{ textTransform: "capitalize" }}>
          {String(name).length > (width - 18) / 7 ? String(name).slice(0, Math.max(1, Math.floor((width - 18) / 7) - 1)) + "…" : name}
        </text>
      )}
      {showCount && (
        <text x={x + 9} y={y + 37} fontSize={11} fill={ink} opacity={0.75}>
          {count} call{count === 1 ? "" : "s"}
        </text>
      )}
    </g>
  );
}

export default function CategoryTreemap({ stats, scope = "" }: { stats: CategoryStat[]; scope?: string }) {
  const router = useRouter();
  // A tile opens the Calls page for that category, limited to real conversations and the same period/agent.
  const callsHref = (key?: string | null) =>
    `/calls?${[scope, "conversation=true", key ? `category=${encodeURIComponent(key)}` : ""].filter(Boolean).join("&")}`;
  if (stats.length === 0) {
    return <div className="text-[12.5px] text-muted py-6 text-center">No categorized calls yet.</div>;
  }

  const data = stats.map((s) => ({
    name: s.category,
    categoryKey: s.key ?? s.category.replace(/ /g, "_"),
    size: s.count,
    count: s.count,
    avg_sentiment: s.avg_sentiment,
    avg_qa: s.avg_qa,
  }));

  return (
    <div>
      <ResponsiveContainer width="100%" height={300}>
        <Treemap data={data} dataKey="size" aspectRatio={4 / 3} content={<Cell onOpen={(key: string) => router.push(callsHref(key))} />} isAnimationActive={false}>
          <Tooltip
            contentStyle={{ background: "#FFFFFF", border: "1px solid #E2E5EC", borderRadius: 6, fontSize: 12 }}
            formatter={() => null as any}
            content={({ payload }) => {
              const p = payload?.[0]?.payload;
              if (!p) return null;
              return (
                <div className="bg-panel border border-hairline rounded-md px-2.5 py-1.5 text-[11.5px] shadow-sm">
                  <div className="text-ink font-medium capitalize">{p.name}</div>
                  <div className="text-muted">
                    {p.count} call{p.count === 1 ? "" : "s"}
                    {p.avg_qa != null && <> · avg QA {p.avg_qa}</>}
                    {p.avg_sentiment != null && <> · sentiment {p.avg_sentiment > 0 ? "+" : ""}{p.avg_sentiment}</>}
                  </div>
                  <div className="text-faint">Click to open these calls</div>
                </div>
              );
            }}
          />
        </Treemap>
      </ResponsiveContainer>
      <div className="flex items-center gap-2 mt-2 text-[10.5px] text-faint">
        <span>Size: call volume · Color:</span>
        <span>negative</span>
        <div className="h-2 w-24 rounded-full" style={{ background: `linear-gradient(to right, ${DIV_LOW}, ${DIV_MID}, ${DIV_HIGH})` }} />
        <span>positive sentiment</span>
      </div>
      <details className="mt-3 text-[12.5px]">
        <summary className="cursor-pointer text-muted hover:text-ink">View as a table</summary>
        <table className="mt-2 w-full text-left">
          <thead className="text-[11px] uppercase tracking-wide text-faint">
            <tr><th className="py-1 font-medium">Category</th><th className="font-medium">Calls</th><th className="font-medium">Avg QA</th><th className="font-medium">Sentiment</th></tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.name} className="border-t border-hairline">
                <td className="py-1.5 capitalize">
                  <Link href={callsHref(d.categoryKey)} className="text-accent hover:underline">{d.name}</Link>
                </td>
                <td className="tabular">{d.count}</td>
                <td className="tabular">{d.avg_qa ?? "—"}</td>
                <td className="tabular">{d.avg_sentiment == null ? "—" : `${d.avg_sentiment > 0 ? "+" : ""}${d.avg_sentiment}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
