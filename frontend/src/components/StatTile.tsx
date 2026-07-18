import { TrendingDown, TrendingUp } from "lucide-react";
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
}

/** Animated KPI tile: GSAP count-up + sparkline + trend arrow. */
export default function StatTile({
  label,
  value,
  suffix = "",
  delta,
  spark,
  color = "#14B8C4",
  icon: Icon,
  invertDelta = false,
}: Props) {
  const ref = useCountUp(value);
  const up = (delta ?? 0) >= 0;
  const good = invertDelta ? !up : up;

  return (
    <GlassCard hover className="reveal-item relative overflow-hidden p-4">
      <div
        className="pointer-events-none absolute -right-6 -top-6 h-20 w-20 rounded-full blur-2xl"
        style={{ backgroundColor: `${color}22` }}
      />
      <div className="flex items-start justify-between">
        <span
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border"
          style={{ color, borderColor: `${color}33`, backgroundColor: `${color}11` }}
        >
          <Icon size={15} />
        </span>
        {delta !== undefined && (
          <span
            className="inline-flex items-center gap-1 font-mono text-[11px] font-semibold"
            style={{ color: good ? "#10B981" : "#EF4444" }}
          >
            {up ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {Math.abs(delta)}%
          </span>
        )}
      </div>
      <div className="mt-3 flex items-end justify-between gap-2">
        <div>
          <div className="font-mono text-2xl font-semibold text-slate-200">
            <span ref={ref}>0</span>
            {suffix}
          </div>
          <div className="mt-0.5 text-[11px] font-medium uppercase tracking-wider text-slate-500">
            {label}
          </div>
        </div>
        {spark && <Sparkline data={spark} color={color} width={84} height={26} />}
      </div>
    </GlassCard>
  );
}
