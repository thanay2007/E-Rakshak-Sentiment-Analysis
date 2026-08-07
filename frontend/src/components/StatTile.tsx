import { HelpCircle, TrendingDown, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useCountUp } from "../hooks/useCountUp";
import GlassCard from "./GlassCard";
import Sparkline from "./Sparkline";

interface Props {
  label: string;
  value: number;
  suffix?: string;
  delta?: number;
  spark?: number[];
  color?: string;
  icon: LucideIcon;
  invertDelta?: boolean; // for metrics where "up" is bad (threats)
  tooltip?: string;
}

/** Animated KPI tile with balanced proportions and uniform height. */
export default function StatTile({
  label,
  value,
  suffix = "",
  delta,
  spark,
  color = "#14B8C4",
  icon: Icon,
  invertDelta = false,
  tooltip,
}: Props) {
  const ref = useCountUp(value);
  const up = (delta ?? 0) >= 0;
  const good = invertDelta ? !up : up;

  return (
    <GlassCard
      hover
      className="reveal-item group relative flex h-[126px] flex-col justify-between overflow-hidden rounded-2xl border border-white/[0.08] bg-base-950/70 p-3.5 backdrop-blur-xl transition-all duration-200 hover:border-white/20 hover:shadow-lg"
    >
      <div
        className="pointer-events-none absolute -right-6 -top-6 h-20 w-20 rounded-full blur-2xl transition-opacity duration-300 group-hover:opacity-100 opacity-40"
        style={{ backgroundColor: `${color}28` }}
      />

      {/* Top row: Icon & Delta Pill */}
      <div className="flex items-center justify-between">
        <span
          className="inline-flex h-8 w-8 items-center justify-center rounded-xl border shadow-sm"
          style={{ color, borderColor: `${color}44`, backgroundColor: `${color}18` }}
        >
          <Icon size={16} />
        </span>

        {delta !== undefined ? (
          <span
            className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10.5px] font-bold tracking-tight shadow-sm"
            style={{
              color: good ? "#10B981" : "#EF4444",
              borderColor: good ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)",
              backgroundColor: good ? "rgba(16, 185, 129, 0.1)" : "rgba(239, 68, 68, 0.1)",
            }}
            title={`24h change: ${up ? "+" : ""}${delta}%`}
          >
            {up ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
            {up ? "+" : ""}{delta}%
          </span>
        ) : (
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
        )}
      </div>

      {/* Bottom row: Value, Label, and Sparkline */}
      <div className="flex items-end justify-between gap-2">
        <div className="min-w-0">
          <div className="font-mono text-2xl font-black tracking-tight text-white">
            <span ref={ref}>0</span>
            {suffix}
          </div>
          <div className="mt-0.5 flex items-center gap-1 text-[11px] font-bold uppercase tracking-wider text-slate-400">
            <span className="truncate">{label}</span>
            {tooltip && (
              <span title={tooltip} className="cursor-help text-slate-500 hover:text-slate-300">
                <HelpCircle size={11} />
              </span>
            )}
          </div>
        </div>

        {spark && (
          <div className="shrink-0 pb-0.5">
            <Sparkline data={spark} color={color} width={64} height={20} />
          </div>
        )}
      </div>
    </GlassCard>
  );
}


