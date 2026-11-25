import Link from "next/link";

export type Trend = {
  current: number | null;
  previous: number | null | undefined;
  /** true: an increase is good (QA, compliance); false: an increase is bad (failures, risk). */
  higherIsBetter: boolean;
  unit?: string;
  decimals?: number;
};

function TrendLine({ trend, label }: { trend: Trend; label: string }) {
  const { current, previous, higherIsBetter, unit = "", decimals = 0 } = trend;
  if (current == null || previous == null) return null;
  const delta = current - previous;
  if (Math.abs(delta) < Math.pow(10, -decimals) / 2) {
    return <div className="text-[11.5px] text-faint mt-1.5">no change {label}</div>;
  }
  const good = delta > 0 === higherIsBetter;
  return (
    <div className={`text-[11.5px] mt-1.5 ${good ? "text-good" : "text-bad"}`}>
      {delta > 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(decimals)}
      {unit} <span className="text-faint">{label}</span>
    </div>
  );
}

export default function MetricCard({
  label,
  value,
  sublabel,
  accent = "default",
  href,
  trend,
  trendLabel = "vs previous period",
}: {
  label: string;
  value: string;
  sublabel?: string;
  accent?: "default" | "good" | "warn" | "bad";
  href?: string;
  trend?: Trend;
  trendLabel?: string;
}) {
  const accentColor = {
    default: "text-ink",
    good: "text-good",
    warn: "text-warn",
    bad: "text-bad",
  }[accent];

  const body = (
    <>
      <div className="text-[11px] uppercase tracking-wider text-faint font-medium mb-2">{label}</div>
      <div className={`font-mono text-[26px] leading-none font-medium tabular ${accentColor}`}>{value}</div>
      {sublabel && <div className="text-[12px] text-muted mt-1.5">{sublabel}</div>}
      {trend && <TrendLine trend={trend} label={trendLabel} />}
    </>
  );
  const base = "bg-panel border border-hairline rounded-lg px-5 py-4 flex-1 min-w-[150px]";
  return href ? (
    <Link href={href} className={`${base} block hover:border-accent/50 transition-colors`}>
      {body}
    </Link>
  ) : (
    <div className={base}>{body}</div>
  );
}
