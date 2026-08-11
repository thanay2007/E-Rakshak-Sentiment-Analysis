import { Activity, Flame, Globe2, Hash, MapPinned, Sparkles, TrendingUp } from "lucide-react";
import { useState } from "react";
import { LanguageChip, SentimentBadge } from "../components/Badges";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import GujaratMap from "../components/GujaratMap";
import { SkeletonChart, SkeletonRow } from "../components/Skeletons";
import Sparkline from "../components/Sparkline";
import { ACCENT, sentimentColor } from "../data/constants";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import type { TermStat } from "../services/api";

const WINDOWS = [
  { label: "6 Hours", hours: 6 },
  { label: "24 Hours", hours: 24 },
  { label: "72 Hours", hours: 72 },
];

function heat(avg: number): string {
  if (avg >= 45) return "#EF4444";
  if (avg >= 30) return "#F59E0B";
  if (avg >= 18) return "#A855F7";
  return "#10B981";
}

function TermRow({ t }: { t: TermStat }) {
  return (
    <div className="reveal-item flex items-center justify-between gap-3 rounded-xl border border-white/[0.06] bg-base-950/60 px-3.5 py-2.5 backdrop-blur-md transition-all hover:border-white/15 hover:bg-base-950/80">
      <div className="flex items-center gap-2.5 min-w-0 flex-1">
        <span className="truncate font-mono text-xs font-bold text-slate-100">{t.term}</span>
        <SentimentBadge label={t.top_label} />
      </div>

      <div className="hidden sm:block">
        <Sparkline data={t.series} color={t.spiking ? "#EF4444" : ACCENT} width={100} height={20} />
      </div>

      <div className="flex items-center gap-2 shrink-0">
        <span className="font-mono text-xs font-bold text-slate-300">{t.count} posts</span>
        {t.spiking ? (
          <span className="inline-flex animate-pulse items-center gap-1 rounded-md border border-threat-critical/40 bg-threat-critical/20 px-2 py-0.5 font-mono text-[10px] font-black text-threat-critical">
            <Flame size={10} /> SPIKE {t.spike_z}σ
          </span>
        ) : (
          <span className={`w-14 text-right font-mono text-xs font-bold ${t.change_pct >= 0 ? "text-threat-neutral" : "text-slate-500"}`}>
            {t.change_pct >= 0 ? "+" : ""}{t.change_pct}%
          </span>
        )}
      </div>
    </div>
  );
}

export default function Trends() {
  const [hours, setHours] = useState(24);
  const { data, loading } = usePolling(() => api.trends(hours), 45000, [hours]);
  const revealRef = useGsapReveal<HTMLDivElement>(`${hours}-${data?.total_posts ?? 0}`);

  return (
    <div ref={revealRef} className="space-y-4">
      {/* Header Command Bar */}
      <div className="flex flex-col gap-3 rounded-2xl border border-white/[0.08] bg-base-950/80 p-4 shadow-xl backdrop-blur-xl md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-accent/40 bg-accent/15 text-accent shadow-[0_0_15px_rgba(20,184,196,0.25)]">
            <TrendingUp size={20} />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-white sm:text-base">
              Real-Time Trend Velocity & Spike Radar
            </h1>
            <p className="text-xs text-slate-400">
              Sliding-window term velocity · Z-score statistical anomalies · Regional threat clustering
            </p>
          </div>
        </div>

        {/* Time Window Buttons */}
        <div className="flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.03] p-1">
          {WINDOWS.map((w) => (
            <button
              key={w.hours}
              onClick={() => setHours(w.hours)}
              className={`rounded-lg px-3 py-1.5 font-mono text-xs font-bold transition-all ${
                hours === w.hours
                  ? "bg-accent text-base-950 shadow-md shadow-accent/20"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {/* 2-Column Trends Grid */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <GlassCard className="p-4 border border-white/[0.08]">
          <SectionTitle
            title="Trending Hashtag Velocity"
            sub="Fastest accelerating hashtags across all ingested platforms"
            right={<Hash size={15} className="text-accent" />}
          />
          {loading && !data ? <SkeletonRow n={6} /> : (
            <div className="mt-3 space-y-2">
              {data?.hashtags.map((t) => <TermRow key={t.term} t={t} />)}
              {data?.hashtags.length === 0 && <p className="py-8 text-center text-xs text-slate-500">No hashtags in selected time window.</p>}
            </div>
          )}
        </GlassCard>

        <GlassCard className="p-4 border border-white/[0.08]">
          <SectionTitle
            title="Trending Threat Keywords"
            sub="NLP evidence terms extracted from high-severity flagged posts"
            right={<Activity size={15} className="text-threat-inflammatory" />}
          />
          {loading && !data ? <SkeletonRow n={6} /> : (
            <div className="mt-3 space-y-2">
              {data?.keywords.map((t) => <TermRow key={t.term} t={t} />)}
              {data?.keywords.length === 0 && <p className="py-8 text-center text-xs text-slate-500">No threat keywords in window.</p>}
            </div>
          )}
        </GlassCard>
      </div>

      {/* Gujarat Regional Heat & Language Distribution */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {/* regional heat */}
        <GlassCard className="p-4 border border-white/[0.08] xl:col-span-2">
          <SectionTitle
            title="Gujarat Regional Threat Heatmap"
            sub="District threat aggregation: circle size = total volume, color = average severity score"
            right={<MapPinned size={15} className="text-accent" />}
          />
          {loading && !data ? <SkeletonChart h={240} /> : (
            <>
              {data && data.regions.length > 0 && <GujaratMap regions={data.regions} />}
              <div className="mt-3.5 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                {data?.regions.map((r) => (
                  <div
                    key={r.name}
                    className="reveal-item relative overflow-hidden rounded-xl border p-3 backdrop-blur-md transition-all hover:scale-[1.02]"
                    style={{ borderColor: `${heat(r.avg_concern)}40`, backgroundColor: `${heat(r.avg_concern)}0f` }}
                  >
                    <div
                      className="pointer-events-none absolute -right-4 -top-4 h-16 w-16 rounded-full blur-xl"
                      style={{ backgroundColor: `${heat(r.avg_concern)}30` }}
                    />
                    <div className="text-xs font-bold text-slate-100">{r.name}</div>
                    <div className="mt-1 font-mono text-xl font-black" style={{ color: heat(r.avg_concern) }}>
                      {r.avg_concern}
                      <span className="ml-1 text-[10px] font-normal text-slate-400">/100</span>
                    </div>
                    <div className="mt-0.5 font-mono text-[10.5px] text-slate-400">
                      {r.count} posts · {r.threats} threats
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.08]">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${Math.min(100, r.avg_concern * 1.4)}%`, backgroundColor: heat(r.avg_concern) }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </GlassCard>

        {/* language breakdown */}
        <GlassCard className="p-4 border border-white/[0.08]">
          <SectionTitle
            title="Language Distribution"
            sub="Detected scripts & code-mixed dialects"
            right={<Globe2 size={15} className="text-accent" />}
          />
          {loading && !data ? <SkeletonChart h={200} /> : (
            <div className="mt-3 space-y-3.5">
              {data?.languages.map((l) => (
                <div key={l.name} className="reveal-item">
                  <div className="flex items-center justify-between text-xs">
                    <LanguageChip language={l.name} />
                    <span className="font-mono font-bold text-slate-300">{l.count} · {l.pct}%</span>
                  </div>
                  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-white/[0.08]">
                    <div
                      className="h-full rounded-full transition-all duration-700 bg-gradient-to-r from-accent to-accent-light"
                      style={{ width: `${l.pct}%` }}
                    />
                  </div>
                </div>
              ))}
              <div className="mt-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 text-[11px] leading-relaxed text-slate-400">
                <strong className="text-accent">Multilingual AI:</strong> Code-mixed romanized dialect (e.g. Hinglish / Gujlish) is normalized into semantic vector embeddings for robust threat scoring.
              </div>
            </div>
          )}
        </GlassCard>
      </div>
    </div>
  );
}
