import { useState } from "react";

/** Geo threat map of Gujarat (inspired by lissy93/twitter-sentiment-visualisation's
 * location-based sentiment views, but fully self-contained: a simplified SVG
 * outline + equirectangular projection, no tile servers or map libraries).
 * Markers are the monitored cities from /api/trends regions — sized by post
 * volume, colored by average threat, pulsing when the region runs hot. */

type Region = { name: string; count: number; avg_threat: number; threats: number; lat: number; lon: number };

// projection bounds (Gujarat): lon 68.0–74.6E, lat 20.0–24.8N
const W = 500, H = 400;
const project = (lat: number, lon: number): [number, number] => [
  ((lon - 68.0) / (74.6 - 68.0)) * W,
  ((24.8 - lat) / (24.8 - 20.0)) * H,
];

// simplified state boundary (lat, lon) — Kutch, mainland, Gulf of Khambhat,
// Saurashtra, Gulf of Kutch — enough to be instantly recognizable
const OUTLINE: [number, number][] = [
  [23.75, 68.15], [24.25, 68.85], [24.35, 69.65], [24.30, 70.55], [24.10, 71.05],
  [24.65, 71.35], [24.45, 72.05], [24.00, 72.55], [23.45, 73.30], [23.05, 73.75],
  [22.75, 74.20], [22.20, 74.30], [21.85, 73.95], [21.30, 73.85], [20.75, 73.60],
  [20.15, 73.00], [20.35, 72.80], [21.05, 72.70], [21.65, 72.60], [22.30, 72.55],
  [21.95, 72.30], [21.60, 72.15], [21.05, 71.50], [20.70, 71.00], [20.90, 70.25],
  [21.60, 69.60], [22.25, 68.95], [22.45, 69.60], [22.80, 70.25], [23.10, 69.65],
  [22.95, 68.90], [23.30, 68.45],
];

const outlinePath =
  OUTLINE.map(([la, lo], i) => `${i === 0 ? "M" : "L"}${project(la, lo).map((v) => v.toFixed(1)).join(",")}`).join(" ") + " Z";

function heat(avg: number): string {
  if (avg >= 45) return "#EF4444";
  if (avg >= 30) return "#F59E0B";
  if (avg >= 18) return "#A855F7";
  return "#10B981";
}

export default function GujaratMap({ regions }: { regions: Region[] }) {
  const [hover, setHover] = useState<Region | null>(null);
  const maxCount = Math.max(1, ...regions.map((r) => r.count));

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Gujarat threat map">
        {/* state silhouette */}
        <path d={outlinePath} fill="rgba(20,184,196,0.05)" stroke="rgba(255,255,255,0.14)" strokeWidth="1.2" strokeLinejoin="round" />
        {/* graticule hint */}
        {[21, 22, 23, 24].map((la) => (
          <line key={la} x1={0} y1={project(la, 68)[1]} x2={W} y2={project(la, 68)[1]} stroke="rgba(255,255,255,0.03)" strokeWidth="1" />
        ))}

        {regions.filter((r) => r.lat && r.lon).map((r) => {
          const [x, y] = project(r.lat, r.lon);
          const radius = 5 + 9 * Math.sqrt(r.count / maxCount);
          const c = heat(r.avg_threat);
          return (
            <g key={r.name} onMouseEnter={() => setHover(r)} onMouseLeave={() => setHover(null)} className="cursor-pointer">
              {r.avg_threat >= 45 && (
                <circle cx={x} cy={y} r={radius + 5} fill="none" stroke={c} strokeWidth="1.5" opacity="0.6" className="animate-ping" style={{ transformOrigin: `${x}px ${y}px` }} />
              )}
              <circle cx={x} cy={y} r={radius} fill={c} fillOpacity="0.22" stroke={c} strokeWidth="1.5" />
              <circle cx={x} cy={y} r={2.5} fill={c} />
              <text x={x} y={y - radius - 5} textAnchor="middle" fill="#94A3B8" fontSize="11" fontFamily="ui-monospace, monospace">
                {r.name}
              </text>
            </g>
          );
        })}
      </svg>

      {hover && (
        <div className="pointer-events-none absolute left-3 top-3 rounded-xl border border-white/10 bg-slate-900/90 px-3 py-2 backdrop-blur">
          <div className="text-[13px] font-semibold text-slate-200">{hover.name}</div>
          <div className="font-mono text-[11px]" style={{ color: heat(hover.avg_threat) }}>
            avg threat {hover.avg_threat}
          </div>
          <div className="font-mono text-[10px] text-slate-500">
            {hover.count} posts · {hover.threats} non-neutral
          </div>
        </div>
      )}

      <div className="mt-1 flex items-center justify-end gap-3 font-mono text-[9.5px] text-slate-600">
        {[["calm", "#10B981"], ["elevated", "#A855F7"], ["high", "#F59E0B"], ["critical", "#EF4444"]].map(([label, c]) => (
          <span key={label} className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: c as string }} /> {label}
          </span>
        ))}
      </div>
    </div>
  );
}
