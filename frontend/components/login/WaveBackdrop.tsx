/**
 * The sign-in page's background: a field of vertical bars, the same waveform that is the product's mark in
 * the sidebar, drawn at poster scale. Pure SVG (a few KB, no image file, works offline in an on-prem
 * install, scales to any screen). The bars breathe slowly; users who ask for reduced motion get it still
 * (see the global prefers-reduced-motion rule).
 */
const BARS = 64;

// Deterministic heights (rounded so the server and the browser always print the same numbers).
const HEIGHTS = Array.from({ length: BARS }, (_, i) => {
  const swell = Math.abs(Math.sin(i * 0.19) * Math.sin(i * 0.063 + 1.1));
  const chatter = Math.abs(Math.sin(i * 0.83 + 0.4));
  return Math.round(36 + swell * 190 + chatter * 46);
});

export default function WaveBackdrop({ className = "" }: { className?: string }) {
  const step = 12.5;
  const width = BARS * step;
  const height = 300;
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      className={className}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="xMidYMax slice"
    >
      <defs>
        <linearGradient id="wave-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#8DB2FF" stopOpacity="0.9" />
          <stop offset="1" stopColor="#2F6FED" stopOpacity="0.15" />
        </linearGradient>
      </defs>
      {HEIGHTS.map((h, i) => (
        <rect
          key={i}
          className="wave-bar"
          style={{ animationDelay: `${-i * 110}ms` }}
          x={i * step + 2}
          y={height - h}
          width="6.5"
          height={h}
          rx="3.25"
          fill="url(#wave-fill)"
        />
      ))}
    </svg>
  );
}
