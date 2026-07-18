import { useState } from "react";

/** Geo threat map of Gujarat, styled as a GEOINT console: graticule with
 * lat/lon labels, corner brackets, radial heat halos around monitored cities,
 * labeled markers with live values, click-to-pin detail card. Fully
 * self-contained SVG (no tile servers). */

type Region = { name: string; count: number; avg_threat: number; threats: number; lat: number; lon: number };

// projection bounds (Gujarat): lon 68.0–74.6E, lat 20.0–24.8N
const W = 560, H = 430;
const project = (lat: number, lon: number): [number, number] => [
  ((lon - 68.0) / (74.6 - 68.0)) * W,
  ((24.8 - lat) / (24.8 - 20.0)) * H,
];

// simplified state boundary (lat, lon)
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

function heatLabel(avg: number): string {
  if (avg >= 45) return "CRITICAL";
  if (avg >= 30) return "HIGH";
  if (avg >= 18) return "ELEVATED";
  return "CALM";
}

export default function GujaratMap({ regions }: { regions: Region[] }) {
  const [pinned, setPinned] = useState<Region | null>(null);
  const [hover, setHover] = useState<Region | null>(null);
  const active = hover ?? pinned;
  const maxCount = Math.max(1, ...regions.map((r) => r.count));

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Gujarat threat map"
           onClick={() => setPinned(null)}>
        <defs>
          {["#EF4444", "#F59E0B", "#A855F7", "#10B981"].map((c) => (
            <radialGradient key={c} id={`halo-${c.slice(1)}`}>
              <stop offset="0%" stopColor={c} stopOpacity="0.35" />
              <stop offset="55%" stopColor={c} stopOpacity="0.12" />
              <stop offset="100%" stopColor={c} stopOpacity="0" />
            </radialGradient>
          ))}
        </defs>

        {/* graticule with coordinate labels */}
        {[21, 22, 23, 24].map((la) => {
          const y = project(la, 68)[1];
          return (
            <g key={`la${la}`}>
              <line x1={0} y1={y} x2={W} y2={y} stroke="rgba(148,163,184,0.06)" strokeWidth="1" strokeDasharray="2 6" />
              <text x={4} y={y - 3} fill="rgba(100,116,139,0.55)" fontSize="7.5" fontFamily="ui-monospace, monospace">
                {la}°N
              </text>
            </g>
          );
        })}
        {[69, 70, 71, 72, 73, 74].map((lo) => {
          const x = project(22, lo)[0];
          return (
            <g key={`lo${lo}`}>
              <line x1={x} y1={0} x2={x} y2={H} stroke="rgba(148,163,184,0.06)" strokeWidth="1" strokeDasharray="2 6" />
              <text x={x + 3} y={H - 5} fill="rgba(100,116,139,0.55)" fontSize="7.5" fontFamily="ui-monospace, monospace">
                {lo}°E
              </text>
            </g>
          );
        })}

        {/* corner brackets */}
        {[[6, 6, 1, 1], [W - 6, 6, -1, 1], [6, H - 6, 1, -1], [W - 6, H - 6, -1, -1]].map(([x, y, sx, sy], i) => (
          <path
            key={i}
            d={`M${x + sx * 14},${y} L${x},${y} L${x},${y + sy * 14}`}
            fill="none"
            stroke="rgba(20,184,196,0.4)"
            strokeWidth="1.5"
          />
        ))}

        {/* state silhouette */}
        <path
          d={outlinePath}
          fill="rgba(20,184,196,0.055)"
          stroke="rgba(94,234,212,0.28)"
          strokeWidth="1.4"
          strokeLinejoin="round"
        />

        {/* city markers */}
        {regions.filter((r) => r.lat && r.lon).map((r) => {
          const [x, y] = project(r.lat, r.lon);
          const radius = 6 + 10 * Math.sqrt(r.count / maxCount);
          const c = heat(r.avg_threat);
          const isActive = active?.name === r.name;
          return (
            <g
              key={r.name}
              onMouseEnter={() => setHover(r)}
              onMouseLeave={() => setHover(null)}
              onClick={(e) => {
                e.stopPropagation();
                setPinned(pinned?.name === r.name ? null : r);
              }}
              className="cursor-pointer"
            >
              {/* heat halo */}
              <circle cx={x} cy={y} r={radius * 2.6} fill={`url(#halo-${c.slice(1)})`} />
              {r.avg_threat >= 45 && (
                <circle
                  cx={x} cy={y} r={radius + 6} fill="none" stroke={c} strokeWidth="1.5" opacity="0.6"
                  className="animate-ping" style={{ transformOrigin: `${x}px ${y}px` }}
                />
              )}
              {/* crosshair ticks */}
              {[[-1, 0], [1, 0], [0, -1], [0, 1]].map(([dx, dy], i) => (
                <line
                  key={i}
                  x1={x + dx * (radius + 3)} y1={y + dy * (radius + 3)}
                  x2={x + dx * (radius + 8)} y2={y + dy * (radius + 8)}
                  stroke={c} strokeWidth="1.2" opacity={isActive ? 0.9 : 0.45}
                />
              ))}
              <circle cx={x} cy={y} r={radius} fill={c} fillOpacity={isActive ? 0.32 : 0.2} stroke={c} strokeWidth="1.6" />
              <circle cx={x} cy={y} r={2.6} fill={c} />

              {/* label pill: name + threat value */}
              <g transform={`translate(${x},${y - radius - 9})`}>
                <rect
                  x={-(r.name.length * 3.4 + 17)} y={-9} width={r.name.length * 6.8 + 34} height={13}
                  rx={6.5} fill="rgba(7,11,22,0.82)" stroke={`${c}55`} strokeWidth="0.8"
                />
                <text textAnchor="middle" y={1} fill="#CBD5E1" fontSize="8.5" fontFamily="ui-monospace, monospace" fontWeight="600">
                  {r.name} <tspan fill={c} fontWeight="700">{r.avg_threat}</tspan>
                </text>
              </g>
            </g>
          );
        })}

        {/* console tag */}
        <text x={W - 8} y={16} textAnchor="end" fill="rgba(94,234,212,0.5)" fontSize="8" fontFamily="ui-monospace, monospace" letterSpacing="2">
          GEOINT · GUJARAT SECTOR
        </text>
      </svg>

      {/* pinned/hover detail card */}
      {active && (
        <div className="pointer-events-none absolute left-3 top-3 min-w-[170px] rounded-xl border bg-slate-900/95 px-3 py-2.5 backdrop-blur"
             style={{ borderColor: `${heat(active.avg_threat)}55` }}>
          <div className="flex items-center justify-between gap-3">
            <span className="text-[13px] font-semibold text-slate-200">{active.name}</span>
            <span
              className="rounded px-1.5 py-0.5 font-mono text-[9px] font-bold"
              style={{ backgroundColor: `${heat(active.avg_threat)}22`, color: heat(active.avg_threat) }}
            >
              {heatLabel(active.avg_threat)}
            </span>
          </div>
          <div className="mt-1.5 grid grid-cols-3 gap-2 text-center">
            {[
              ["threat", active.avg_threat],
              ["posts", active.count],
              ["flagged", active.threats],
            ].map(([k, v]) => (
              <div key={k}>
                <div className="font-mono text-sm font-bold" style={{ color: k === "threat" ? heat(active.avg_threat) : "#E2E8F0" }}>
                  {v}
                </div>
                <div className="text-[8.5px] uppercase tracking-widest text-slate-500">{k}</div>
              </div>
            ))}
          </div>
          <div className="mt-1 font-mono text-[9px] text-slate-600">
            {active.lat.toFixed(2)}°N {active.lon.toFixed(2)}°E{pinned?.name === active.name ? " · pinned" : ""}
          </div>
        </div>
      )}

      <div className="mt-1 flex items-center justify-between font-mono text-[9.5px] text-slate-600">
        <span>click a city to pin its readout</span>
        <div className="flex items-center gap-3">
          {[["calm", "#10B981"], ["elevated", "#A855F7"], ["high", "#F59E0B"], ["critical", "#EF4444"]].map(([label, c]) => (
            <span key={label} className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: c as string }} /> {label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
