import { useState } from "react";
import { ExternalLink, MapPin, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

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
  const navigate = useNavigate();
  const [pinned, setPinned] = useState<Region | null>(null);
  const [hover, setHover] = useState<Region | null>(null);
  const active = pinned ?? hover;
  const maxCount = Math.max(1, ...regions.map((r) => r.count));

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full select-none"
        role="img"
        aria-label="Gujarat threat map"
        onClick={() => setPinned(null)}
      >
        <defs>
          {["#EF4444", "#F59E0B", "#A855F7", "#10B981"].map((c) => (
            <radialGradient key={c} id={`halo-${c.slice(1)}`}>
              <stop offset="0%" stopColor={c} stopOpacity="0.45" />
              <stop offset="55%" stopColor={c} stopOpacity="0.18" />
              <stop offset="100%" stopColor={c} stopOpacity="0" />
            </radialGradient>
          ))}
        </defs>

        {/* graticule with coordinate labels */}
        {[21, 22, 23, 24].map((la) => {
          const y = project(la, 68)[1];
          return (
            <g key={`la${la}`}>
              <line x1={0} y1={y} x2={W} y2={y} stroke="rgba(148,163,184,0.08)" strokeWidth="1" strokeDasharray="2 6" />
              <text x={4} y={y - 3} fill="rgba(148,163,184,0.7)" fontSize="8" fontFamily="ui-monospace, monospace">
                {la}°N
              </text>
            </g>
          );
        })}
        {[69, 70, 71, 72, 73, 74].map((lo) => {
          const x = project(22, lo)[0];
          return (
            <g key={`lo${lo}`}>
              <line x1={x} y1={0} x2={x} y2={H} stroke="rgba(148,163,184,0.08)" strokeWidth="1" strokeDasharray="2 6" />
              <text x={x + 3} y={H - 5} fill="rgba(148,163,184,0.7)" fontSize="8" fontFamily="ui-monospace, monospace">
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
            stroke="rgba(20,184,196,0.6)"
            strokeWidth="1.5"
          />
        ))}

        {/* state silhouette */}
        <path
          d={outlinePath}
          fill="rgba(20,184,196,0.07)"
          stroke="rgba(94,234,212,0.4)"
          strokeWidth="1.6"
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
              className="cursor-pointer transition-all duration-200"
            >
              {/* heat halo */}
              <circle cx={x} cy={y} r={radius * 2.6} fill={`url(#halo-${c.slice(1)})`} />
              {r.avg_threat >= 45 && (
                <circle
                  cx={x} cy={y} r={radius + 6} fill="none" stroke={c} strokeWidth="1.5" opacity="0.7"
                  className="animate-ping" style={{ transformOrigin: `${x}px ${y}px` }}
                />
              )}
              {/* crosshair ticks */}
              {[[-1, 0], [1, 0], [0, -1], [0, 1]].map(([dx, dy], i) => (
                <line
                  key={i}
                  x1={x + dx * (radius + 3)} y1={y + dy * (radius + 3)}
                  x2={x + dx * (radius + 8)} y2={y + dy * (radius + 8)}
                  stroke={c} strokeWidth="1.4" opacity={isActive ? 1 : 0.6}
                />
              ))}
              <circle cx={x} cy={y} r={radius} fill={c} fillOpacity={isActive ? 0.45 : 0.25} stroke={c} strokeWidth="1.8" />
              <circle cx={x} cy={y} r={3} fill="#FFFFFF" />

              {/* label pill: name + threat value */}
              <g transform={`translate(${x},${y - radius - 10})`}>
                <rect
                  x={-(r.name.length * 3.6 + 20)} y={-10} width={r.name.length * 7.2 + 40} height={15}
                  rx={7.5} fill="rgba(10,15,30,0.92)" stroke={`${c}88`} strokeWidth="1"
                />
                <text textAnchor="middle" y={1.5} fill="#F1F5F9" fontSize="9" fontFamily="ui-monospace, monospace" fontWeight="600">
                  {r.name} <tspan fill={c} fontWeight="800">· {r.avg_threat}</tspan>
                </text>
              </g>
            </g>
          );
        })}

        {/* console tag */}
        <text x={W - 8} y={16} textAnchor="end" fill="rgba(94,234,212,0.8)" fontSize="8.5" fontFamily="ui-monospace, monospace" letterSpacing="2" fontWeight="600">
          GEOINT · GUJARAT SECTOR
        </text>
      </svg>

      {/* pinned/hover detail card */}
      {active && (
        <div
          className="absolute left-3 top-3 z-10 min-w-[200px] rounded-2xl border bg-slate-950/95 p-3.5 shadow-2xl backdrop-blur-md"
          style={{ borderColor: `${heat(active.avg_threat)}80` }}
        >
          <div className="flex items-center justify-between gap-2 border-b border-white/[0.08] pb-2">
            <div className="flex items-center gap-1.5">
              <MapPin size={13} style={{ color: heat(active.avg_threat) }} />
              <span className="text-sm font-bold text-slate-100">{active.name}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span
                className="rounded-md px-1.5 py-0.5 font-mono text-[9px] font-extrabold uppercase"
                style={{ backgroundColor: `${heat(active.avg_threat)}25`, color: heat(active.avg_threat) }}
              >
                {heatLabel(active.avg_threat)}
              </span>
              {pinned?.name === active.name && (
                <button onClick={() => setPinned(null)} className="text-slate-400 hover:text-white" title="Unpin">
                  <X size={12} />
                </button>
              )}
            </div>
          </div>

          <div className="mt-2.5 grid grid-cols-3 gap-2 text-center">
            {[
              ["avg threat", active.avg_threat],
              ["total posts", active.count],
              ["threat alerts", active.threats],
            ].map(([k, v]) => (
              <div key={k} className="rounded-lg bg-white/[0.03] p-1.5">
                <div className="font-mono text-sm font-bold" style={{ color: k.includes("threat") ? heat(active.avg_threat) : "#F8FAFC" }}>
                  {v}
                </div>
                <div className="text-[8px] uppercase tracking-wider text-slate-400">{k}</div>
              </div>
            ))}
          </div>

          <div className="mt-2.5 flex items-center justify-between border-t border-white/[0.06] pt-2 text-[10px]">
            <span className="font-mono text-slate-400">
              {active.lat.toFixed(2)}°N {active.lon.toFixed(2)}°E
            </span>
            <button
              onClick={() => navigate(`/app/feed?location=${encodeURIComponent(active.name)}`)}
              className="inline-flex items-center gap-1 font-semibold text-accent hover:underline"
            >
              Feed <ExternalLink size={10} />
            </button>
          </div>
        </div>
      )}

      {/* Map Legend */}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-1.5 font-mono text-[10.5px] text-slate-400">
        <span>Click any district marker to pin geospatial metrics</span>
        <div className="flex items-center gap-3">
          {[["Calm (<18)", "#10B981"], ["Elevated (18-29)", "#A855F7"], ["High (30-44)", "#F59E0B"], ["Critical (45+)", "#EF4444"]].map(([label, c]) => (
            <span key={label} className="inline-flex items-center gap-1 font-medium">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: c }} /> {label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

