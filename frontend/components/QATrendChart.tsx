"use client";

import { useState } from "react";
import { QATrendPoint } from "@/lib/api";

/**
 * Daily average QA score as a plain SVG line (no chart library) with the target drawn as a
 * dashed line. Hover (or touch) anywhere on the chart: it snaps to the nearest day and shows
 * the date, score and number of calls, so there is no tiny dot to aim for.
 */
export default function QATrendChart({ points, target }: { points: QATrendPoint[]; target: number }) {
  const [hover, setHover] = useState<number | null>(null);

  if (points.length < 2) {
    return (
      <div className="text-[12.5px] text-muted py-8 text-center">
        {points.length === 0 ? "No scored calls in this period." : "Need at least two days of scored calls to draw a trend."}
      </div>
    );
  }
  const W = 560, H = 240, PX = 34, PY = 18, RIGHT = 10;
  const x = (i: number) => PX + (i / (points.length - 1)) * (W - PX - RIGHT);
  const y = (v: number) => PY + (1 - Math.max(0, Math.min(100, v)) / 100) * (H - PY * 2);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.avg_qa).toFixed(1)}`).join(" ");

  const pick = (e: React.MouseEvent<SVGSVGElement> | React.TouchEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const clientX = "touches" in e ? e.touches[0]?.clientX : e.clientX;
    if (clientX === undefined || rect.width === 0) return;
    const vx = ((clientX - rect.left) / rect.width) * W;           // into viewBox units
    const i = Math.round(((vx - PX) / (W - PX - RIGHT)) * (points.length - 1));
    setHover(Math.max(0, Math.min(points.length - 1, i)));
  };

  const hp = hover !== null ? points[hover] : null;
  const label = hp ? `${hp.day}  ·  avg ${hp.avg_qa}  ·  ${hp.calls} call${hp.calls === 1 ? "" : "s"}` : "";
  const boxW = 150;
  const boxX = hover !== null ? Math.max(PX, Math.min(W - RIGHT - boxW, x(hover) - boxW / 2)) : 0;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full h-auto cursor-crosshair select-none"
      role="img"
      aria-label="Average QA score by day"
      onMouseMove={pick}
      onMouseLeave={() => setHover(null)}
      onTouchStart={pick}
      onTouchMove={pick}
      onTouchEnd={() => setHover(null)}
    >
      {[0, 50, 100].map((g) => (
        <g key={g}>
          <line x1={PX} x2={W - RIGHT} y1={y(g)} y2={y(g)} stroke="#E4E7EE" strokeWidth="1" />
          <text x={PX - 6} y={y(g) + 3} textAnchor="end" fontSize="10" fill="#6C7488">{g}</text>
        </g>
      ))}
      <line x1={PX} x2={W - RIGHT} y1={y(target)} y2={y(target)} stroke="#12805A" strokeWidth="1" strokeDasharray="4 3" />
      <text x={W - RIGHT - 2} y={y(target) - 4} textAnchor="end" fontSize="10" fill="#12805A">target {target}</text>
      <path d={path} fill="none" stroke="#2F6FED" strokeWidth="2" strokeLinejoin="round" />
      {points.map((p, i) => (
        <circle key={p.day} cx={x(i)} cy={y(p.avg_qa)} r={hover === i ? 5 : 2.5} fill="#2F6FED" />
      ))}
      <text x={PX} y={H - 2} fontSize="10" fill="#6C7488">{points[0].day.slice(5)}</text>
      <text x={W - RIGHT} y={H - 2} textAnchor="end" fontSize="10" fill="#6C7488">{points[points.length - 1].day.slice(5)}</text>

      {hp && hover !== null && (
        <g pointerEvents="none">
          <line x1={x(hover)} x2={x(hover)} y1={PY} y2={H - PY} stroke="#2F6FED" strokeWidth="1" strokeOpacity="0.35" />
          <rect x={boxX} y={2} width={boxW} height={20} rx={4} fill="#1B2030" />
          <text x={boxX + boxW / 2} y={16} textAnchor="middle" fontSize="10.5" fill="#fff">{label}</text>
        </g>
      )}
    </svg>
  );
}
