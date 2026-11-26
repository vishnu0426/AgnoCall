/**
 * A small, static picture of what is inside the product, shown on the sign-in page. Decorative only
 * (hidden from screen readers) and clearly labelled as sample data, so it never reads as real results.
 */
const TREND = [58, 61, 57, 64, 66, 63, 70, 72, 69, 75, 78, 80];

function sparkline(width: number, height: number): string {
  const lo = 40;
  const hi = 100;
  return TREND.map((v, i) => {
    const x = Math.round((i / (TREND.length - 1)) * width * 10) / 10;
    const y = Math.round((height - ((v - lo) / (hi - lo)) * height) * 10) / 10;
    return `${i === 0 ? "M" : "L"}${x},${y}`;
  }).join(" ");
}

export default function ProductPreview() {
  const w = 396;
  const h = 64;
  const targetY = Math.round((h - ((80 - 40) / 60) * h) * 10) / 10;
  return (
    <figure aria-hidden="true" className="m-0 w-full max-w-[460px] select-none">
      <div className="rounded-xl bg-white/95 p-5 text-ink shadow-[0_24px_60px_-20px_rgba(2,8,30,0.7)] ring-1 ring-white/40">
        <div className="mb-4 flex items-center justify-between">
          <span className="font-display text-[13px] font-semibold">QA overview</span>
          <span className="rounded-full bg-panelRaised px-2.5 py-0.5 text-[11px] text-faint">Last 30 days</span>
        </div>

        <div className="grid grid-cols-3 gap-3">
          {[
            { label: "Avg QA score", value: "82", tone: "text-good" },
            { label: "Compliance", value: "96%", tone: "text-ink" },
            { label: "Calls scored", value: "1,284", tone: "text-ink" },
          ].map((k) => (
            <div key={k.label} className="rounded-lg border border-hairline px-3 py-2.5">
              <div className="text-[10.5px] uppercase tracking-wide text-faint">{k.label}</div>
              <div className={`mt-0.5 font-mono text-[20px] font-semibold tabular ${k.tone}`}>{k.value}</div>
            </div>
          ))}
        </div>

        <svg viewBox={`0 0 ${w} ${h + 8}`} className="mt-4 h-[64px] w-full" preserveAspectRatio="none">
          <line x1="0" x2={w} y1={targetY + 4} y2={targetY + 4} stroke="#12805A" strokeWidth="1" strokeDasharray="4 3" />
          <path d={sparkline(w, h)} transform="translate(0 4)" fill="none" stroke="#2F6FED" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        </svg>

        <div className="mt-4 flex items-start gap-3 rounded-lg border border-[#C1352E]/25 bg-[#C1352E]/5 px-3 py-2.5">
          <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-bad" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2 text-[12px] font-medium">
              <span>Possible compliance issue</span>
              <span className="font-mono text-[11px] text-faint">02:14</span>
            </div>
            <div className="mt-0.5 truncate text-[12px] italic text-muted">&ldquo;I can guarantee you a full refund.&rdquo;</div>
          </div>
        </div>
      </div>
      <figcaption className="mt-2.5 text-center text-[11px] text-[#9FB3E3]">Illustration with sample data</figcaption>
    </figure>
  );
}
