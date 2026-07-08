import { Flame, Hash, MapPinned, TrendingUp } from "lucide-react";
import { useState } from "react";
import { LanguageChip, ThreatBadge } from "../components/Badges";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import { SkeletonChart, SkeletonRow } from "../components/Skeletons";
import Sparkline from "../components/Sparkline";
import { ACCENT, THREAT_COLORS } from "../data/constants";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import type { TermStat } from "../services/api";

const WINDOWS = [
  { label: "6h", hours: 6 },
  { label: "24h", hours: 24 },
  { label: "72h", hours: 72 },
];

function heat(avg: number): string {
  if (avg >= 45) return "#EF4444";
  if (avg >= 30) return "#F59E0B";
  if (avg >= 18) return "#A855F7";
  return "#10B981";
}

function TermRow({ t }: { t: TermStat }) {
  return (
    <div className="reveal-item flex items-center gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2.5">
      <span className="w-36 truncate text-[12.5px] font-medium text-slate-200">{t.term}</span>
      <ThreatBadge label={t.top_label} />
      <Sparkline data={t.series} color={t.spiking ? "#EF4444" : ACCENT} width={110} height={24} />
      <span className="ml-auto font-mono text-xs text-slate-400">{t.count}</span>
      {t.spiking ? (
        <span className="inline-flex animate-pulse-slow items-center gap-1 rounded-md bg-threat-critical/15 px-2 py-0.5 font-mono text-[10px] font-bold text-threat-critical">
          <Flame size={10} /> SPIKE {t.spike_z}σ
        </span>
      ) : (
        <span className={`w-14 text-right font-mono text-[11px] ${t.change_pct >= 0 ? "text-threat-neutral" : "text-slate-600"}`}>
          {t.change_pct >= 0 ? "+" : ""}{t.change_pct}%
        </span>
      )}
    </div>
  );
}

export default function Trends() {
  const [hours, setHours] = useState(24);
  const { data, loading } = usePolling(() => api.trends(hours), 45000, [hours]);
  const revealRef = useGsapReveal<HTMLDivElement>(`${hours}-${data?.total_posts ?? 0}`);

  return (
    <div ref={revealRef} className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-bold text-slate-200">
            <TrendingUp size={18} className="text-accent" /> Trend Intelligence
          </h1>
          <p className="text-xs text-slate-500">
            sliding-window term velocity · z-score spike detection · regional heat
          </p>
        </div>
        <div className="flex gap-1.5">
          {WINDOWS.map((w) => (
            <button
              key={w.hours}
              onClick={() => setHours(w.hours)}
              className={`rounded-xl border px-3 py-1.5 font-mono text-xs transition-all ${
                hours === w.hours
                  ? "border-accent/50 bg-accent/10 text-accent"
                  : "border-white/10 text-slate-500 hover:text-slate-300"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <GlassCard className="p-4">
          <SectionTitle title="Trending Hashtags" right={<Hash size={14} className="text-slate-600" />} />
          {loading && !data ? <SkeletonRow n={6} /> : (
            <div className="space-y-2">
              {data?.hashtags.map((t) => <TermRow key={t.term} t={t} />)}
              {data?.hashtags.length === 0 && <p className="py-6 text-center text-xs text-slate-500">No hashtags in window.</p>}
            </div>
          )}
        </GlassCard>

        <GlassCard className="p-4">
          <SectionTitle title="Trending Threat Keywords" sub="NLP evidence terms from flagged posts" />
          {loading && !data ? <SkeletonRow n={6} /> : (
            <div className="space-y-2">
              {data?.keywords.map((t) => <TermRow key={t.term} t={t} />)}
              {data?.keywords.length === 0 && <p className="py-6 text-center text-xs text-slate-500">No keywords in window.</p>}
            </div>
          )}
        </GlassCard>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {/* regional heat */}
        <GlassCard className="p-4 xl:col-span-2">
          <SectionTitle
            title="Gujarat Regional Heat"
            sub="average threat score by monitored location"
            right={<MapPinned size={14} className="text-slate-600" />}
          />
          {loading && !data ? <SkeletonChart h={230} /> : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {data?.regions.map((r) => (
                <div
                  key={r.name}
                  className="reveal-item relative overflow-hidden rounded-xl border p-3"
                  style={{ borderColor: `${heat(r.avg_threat)}33`, backgroundColor: `${heat(r.avg_threat)}0d` }}
                >
                  <div
                    className="pointer-events-none absolute -right-4 -top-4 h-16 w-16 rounded-full blur-xl"
                    style={{ backgroundColor: `${heat(r.avg_threat)}2e` }}
                  />
                  <div className="text-[13px] font-semibold text-slate-200">{r.name}</div>
                  <div className="mt-1 font-mono text-2xl font-bold" style={{ color: heat(r.avg_threat) }}>
                    {r.avg_threat}
                  </div>
                  <div className="mt-0.5 font-mono text-[10px] text-slate-500">
                    {r.count} posts · {r.threats} threats
                  </div>
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.07]">
                    <div className="h-full rounded-full" style={{ width: `${Math.min(100, r.avg_threat * 1.4)}%`, backgroundColor: heat(r.avg_threat) }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>

        {/* language breakdown */}
        <GlassCard className="p-4">
          <SectionTitle title="Language Breakdown" sub="detected by script + marker analysis" />
          {loading && !data ? <SkeletonChart h={200} /> : (
            <div className="space-y-3">
              {data?.languages.map((l) => (
                <div key={l.name} className="reveal-item">
                  <div className="flex items-center justify-between text-xs">
                    <LanguageChip language={l.name} />
                    <span className="font-mono text-slate-400">{l.count} · {l.pct}%</span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                    <div
                      className="h-full rounded-full transition-all duration-700"
                      style={{ width: `${l.pct}%`, backgroundColor: ACCENT }}
                    />
                  </div>
                </div>
              ))}
              <p className="pt-2 text-[10.5px] leading-relaxed text-slate-600">
                Code-mixed romanized content (Hinglish) is classified with the same
                pipeline as native-script text — the segment generic tools miss.
              </p>
            </div>
          )}
        </GlassCard>
      </div>
    </div>
  );
}
