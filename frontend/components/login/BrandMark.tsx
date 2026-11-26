/** The product's waveform mark (same bars as the sidebar), with a light variant for dark backgrounds. */
const HEIGHTS = [4, 9, 14, 8, 16, 6, 11, 5];

export default function BrandMark({ light = false, size = 1 }: { light?: boolean; size?: number }) {
  return (
    <svg width={22 * size} height={18 * size} viewBox="0 0 22 18" fill="none" aria-hidden="true">
      {HEIGHTS.map((h, i) => (
        <rect
          key={i}
          x={i * 2.7}
          y={9 - h / 2}
          width="1.6"
          height={h}
          rx="0.8"
          fill={i % 3 === 0 ? (light ? "#8DB2FF" : "#2F6FED") : light ? "#FFFFFF" : "#6C7488"}
        />
      ))}
    </svg>
  );
}
