import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity, ArrowUpRight, Download, Flame, Globe2, Hash, MapPinned, Search,
  TrendingUp,
} from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { LanguageChip, PlatformIcon, SentimentBadge } from "../components/Badges";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import GujaratMap from "../components/GujaratMap";
import { SkeletonChart, SkeletonRow } from "../components/Skeletons";
import Sparkline from "../components/Sparkline";
import { ACCENT } from "../data/constants";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { useUrlFilters } from "../hooks/useUrlFilters";
import { api } from "../services/api";
import type { TermStat } from "../services/api";

const WINDOWS = [
  { label: "6H", hours: 6 },
  { label: "24H", hours: 24 },
  { label: "72H", hours: 72 },
  { label: "7D", hours: 168 },
];

const SENTIMENT_COLORS: Record<string, string> = {
  negative: "#EF4444",
  neutral: "#64748B",
  positive: "#10B981",
};

const TOOLTIP_STYLE = {
  background: "rgba(2,6,23,0.95)",
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: 12,
  fontSize: 12,
};

function heat(avg: number): string {
  if (avg >= 45) return "#EF4444";
  if (avg >= 30) return "#F59E0B";
  if (avg >= 18) return "#A855F7";
  return "#10B981";
}

/** One term. Clicking it opens the feed already filtered to that term — a trend
 *  you cannot drill into is a number with nothing behind it. */
function TermRow({ t }: { t: TermStat }) {
  const href = `/app/feed?q=${encodeURIComponent(t.term)}`;
  return (
    <Link
      to={href}
      className="reveal-item group flex items-center justify-between gap-3 rounded-xl border border-white/[0.06] bg-base-950/60 px-3.5 py-2.5 backdrop-blur-md transition-all hover:border-accent/30 hover:bg-base-950/80"
    >
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <span className="truncate font-mono text-xs font-bold text-slate-100">
          {t.kind === "hashtag" ? "#" : ""}{t.term}
        </span>
        <SentimentBadge label={t.top_label} />
        {t.negative_share >= 0.5 && (
          <span className="shrink-0 font-mono text-[10px] font-bold text-threat-critical">
            {Math.round(t.negative_share * 100)}% neg
          </span>
        )}
      </div>

      <div className="hidden sm:block">
        <Sparkline data={t.series} color={t.spiking ? "#EF4444" : ACCENT} width={100} height={20} />
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <span className="font-mono text-xs font-bold text-slate-300">{t.count}</span>
        {t.spiking ? (
          <span className="inline-flex animate-pulse items-center gap-1 rounded-md border border-threat-critical/40 bg-threat-critical/20 px-2 py-0.5 font-mono text-[10px] font-black text-threat-critical">
            <Flame size={10} /> {t.spike_z}σ
          </span>
        ) : (
          <span className={`w-12 text-right font-mono text-xs font-bold ${t.change_pct >= 0 ? "text-threat-neutral" : "text-slate-500"}`}>
            {t.change_pct >= 0 ? "+" : ""}{t.change_pct}%
          </span>
        )}
        <ArrowUpRight size={13} className="text-slate-700 transition-colors group-hover:text-accent" />
      </div>
    </Link>
  );
}

export default function Trends() {
  // URL-backed so the assistant can open this page on a given window.
  const { getNumber, set } = useUrlFilters();
  const hours = getNumber("hours", 24);
  const setHours = (value: number) => set("hours", value);
  const [query, setQuery] = useState("");
  const { data, loading } = usePolling(() => api.trends(hours), 45000, [hours]);
  const revealRef = useGsapReveal<HTMLDivElement>(`${hours}-${data?.total_posts ?? 0}`);

  const q = query.trim().toLowerCase();
  const hashtags = (data?.hashtags ?? []).filter((t) => !q || t.term.toLowerCase().includes(q));
  const keywords = (data?.keywords ?? []).filter((t) => !q || t.term.toLowerCase().includes(q));

  const spiking = useMemo(
    () => [...(data?.hashtags ?? []), ...(data?.keywords ?? [])]
      .filter((t) => t.spiking)
      .sort((a, b) => b.spike_z - a.spike_z),
    [data]
  );

  const totals = data?.sentiment_totals;
  const negShare = totals && data
    ? Math.round((totals.negative / Math.max(1, data.total_posts)) * 100)
    : 0;

  const exportTerms = () => {
    const rows = [["kind", "term", "count", "change_pct", "spike_z", "spiking", "top_label", "negative_share"]];
    for (const t of [...(data?.hashtags ?? []), ...(data?.keywords ?? [])]) {
      rows.push([t.kind, t.term, String(t.count), String(t.change_pct),
        String(t.spike_z), String(t.spiking), t.top_label, String(t.negative_share)]);
    }
    const csv = rows.map((r) => r.map((c) => `"${c.replace(/"/g, '""')}"`).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `trends_${hours}h.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

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
              Sentiment Trends & Sudden Spikes
            </h1>
            <p className="text-xs text-slate-400">
              How the mood has changed, which words are suddenly rising, and where — by platform, language and district
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={exportTerms}
            disabled={!data}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-bold text-slate-200 transition-all hover:bg-white/[0.08] hover:text-accent disabled:opacity-40"
          >
            <Download size={13} /> Export CSV
          </button>
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
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Posts in window", data?.total_posts ?? 0, "#14B8C4"],
          ["Negative share", `${negShare}%`, negShare >= 35 ? "#EF4444" : "#F59E0B"],
          ["Avg concern", data?.avg_concern ?? 0, "#A855F7"],
          ["Terms spiking", spiking.length, spiking.length ? "#EF4444" : "#10B981"],
        ].map(([label, value, color]) => (
          <GlassCard key={label as string} className="p-3.5">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</div>
            <div className="mt-1 font-mono text-2xl font-black" style={{ color: color as string }}>
              {typeof value === "number" ? value.toLocaleString() : value}
            </div>
          </GlassCard>
        ))}
      </div>

      {/* Spike banner — the one thing on this page that wants acting on now. */}
      {spiking.length > 0 && (
        <GlassCard className="border-threat-critical/30 bg-threat-critical/[0.04] p-3.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-black uppercase tracking-wider text-threat-critical">
              <Flame size={14} /> Spiking now
            </span>
            {spiking.slice(0, 8).map((t) => (
              <Link key={`${t.kind}-${t.term}`} to={`/app/feed?q=${encodeURIComponent(t.term)}`}
                className="rounded-lg border border-threat-critical/40 bg-threat-critical/10 px-2 py-0.5 font-mono text-[11px] font-bold text-threat-critical hover:bg-threat-critical/20">
                {t.kind === "hashtag" ? "#" : ""}{t.term} <span className="opacity-70">{t.spike_z}σ</span>
              </Link>
            ))}
            <Link to="/app/watchlist" className="ml-auto text-[11px] font-semibold text-accent hover:underline">
              add to watchlist →
            </Link>
          </div>
        </GlassCard>
      )}

      {/* Sentiment over time — the chart this page is named after. */}
      <GlassCard className="p-4">
        <SectionTitle
          title="Sentiment Over Time"
          sub={`How many posts were positive, negative or neutral in the last ${hours < 72 ? `${hours} hours` : `${hours / 24} days`}`}
          right={<Activity size={15} className="text-accent" />}
        />
        {loading && !data ? <SkeletonChart h={260} /> : (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data?.sentiment_series ?? []} margin={{ top: 6, right: 12, left: -14, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="rgba(255,255,255,0.08)" strokeDasharray="3 3" />
              <XAxis dataKey="label" tickLine={false} axisLine={false} interval="preserveStartEnd"
                tick={{ fill: "#94A3B8", fontSize: 11 }} />
              <YAxis tickLine={false} axisLine={false} width={46} allowDecimals={false}
                tick={{ fill: "#94A3B8", fontSize: 11 }} />
              <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="negative" name="Negative" stackId="s" fill={SENTIMENT_COLORS.negative} />
              <Bar dataKey="neutral" name="Neutral" stackId="s" fill={SENTIMENT_COLORS.neutral} />
              <Bar dataKey="positive" name="Positive" stackId="s" fill={SENTIMENT_COLORS.positive} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </GlassCard>

      {/* Term velocity */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <GlassCard className="p-4">
          <SectionTitle
            title="Trending Hashtags"
            sub="Tags rising fastest right now — click one to read those posts"
            right={
              <div className="relative">
                <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="filter terms…"
                  className="w-36 rounded-lg border border-white/[0.1] bg-white/[0.04] py-1 pl-7 pr-2 text-[11px] text-slate-100 placeholder:text-slate-600 focus:border-accent/60 focus:outline-none"
                />
              </div>
            }
          />
          {loading && !data ? <SkeletonRow n={6} /> : (
            <div className="mt-3 space-y-2">
              {hashtags.map((t) => <TermRow key={t.term} t={t} />)}
              {hashtags.length === 0 && (
                <p className="py-8 text-center text-xs text-slate-500">
                  {q ? "No hashtags match that filter." : "No hashtags in this window."}
                </p>
              )}
            </div>
          )}
        </GlassCard>

        <GlassCard className="p-4">
          <SectionTitle
            title="Trending Keywords"
            sub="Words appearing most often in the posts we checked"
            right={<Hash size={15} className="text-threat-inflammatory" />}
          />
          {loading && !data ? <SkeletonRow n={6} /> : (
            <div className="mt-3 space-y-2">
              {keywords.map((t) => <TermRow key={t.term} t={t} />)}
              {keywords.length === 0 && (
                <p className="py-8 text-center text-xs text-slate-500">
                  {q ? "No keywords match that filter." : "No keywords in this window."}
                </p>
              )}
            </div>
          )}
        </GlassCard>
      </div>

      {/* Platform split */}
      <GlassCard className="p-4">
        <SectionTitle
          title="Where It Is Being Said"
          sub="How many posts on each platform and how angry they are — click to read them"
          right={<Globe2 size={15} className="text-accent" />}
        />
        {loading && !data ? <SkeletonRow n={3} /> : (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {(data?.platforms ?? []).map((p) => {
              const negPct = Math.round((p.negative / Math.max(1, p.count)) * 100);
              return (
                <Link key={p.name} to={`/app/feed?platform=${encodeURIComponent(p.name)}`}
                  className="reveal-item rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 transition-all hover:border-accent/30">
                  <div className="flex items-center gap-2">
                    <PlatformIcon platform={p.name} size={16} />
                    <span className="text-xs font-bold text-slate-100">{p.name}</span>
                    <span className="ml-auto font-mono text-sm font-black text-slate-200">
                      {p.count.toLocaleString()}
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.08]">
                    <div className="h-full rounded-full bg-threat-critical/80" style={{ width: `${negPct}%` }} />
                  </div>
                  <div className="mt-1.5 flex justify-between font-mono text-[10.5px] text-slate-500">
                    <span>{negPct}% negative</span>
                    <span>avg concern {p.avg_concern}</span>
                  </div>
                </Link>
              );
            })}
            {(data?.platforms ?? []).length === 0 && (
              <p className="col-span-full py-6 text-center text-xs text-slate-500">No platform activity in this window.</p>
            )}
          </div>
        )}
      </GlassCard>

      {/* Gujarat Regional Heat & Language Distribution */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <GlassCard className="p-4 xl:col-span-2">
          <SectionTitle
            title="District Heatmap"
            sub="Bigger circle = more posts · Redder colour = higher concern"
            right={<MapPinned size={15} className="text-accent" />}
          />
          {loading && !data ? <SkeletonChart h={240} /> : (
            <>
              {data && data.regions.length > 0 && <GujaratMap regions={data.regions} />}
              <div className="mt-3.5 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                {data?.regions.map((r) => (
                  <Link
                    key={r.name}
                    to={`/app/feed?location=${encodeURIComponent(r.name)}`}
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
                      {r.count} posts · {r.threats} negative
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.08]">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${Math.min(100, r.avg_concern * 1.4)}%`, backgroundColor: heat(r.avg_concern) }}
                      />
                    </div>
                  </Link>
                ))}
              </div>
            </>
          )}
        </GlassCard>

        <GlassCard className="p-4">
          <SectionTitle
            title="Language Distribution"
            sub="Which languages the posts are written in, including mixed ones"
            right={<Globe2 size={15} className="text-accent" />}
          />
          {loading && !data ? <SkeletonChart h={200} /> : (
            <div className="mt-3 space-y-3.5">
              {data?.languages.map((l) => (
                <Link key={l.name} to={`/app/feed?language=${encodeURIComponent(l.name)}`} className="reveal-item block">
                  <div className="flex items-center justify-between text-xs">
                    <LanguageChip language={l.name} />
                    <span className="font-mono font-bold text-slate-300">{l.count} · {l.pct}%</span>
                  </div>
                  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-white/[0.08]">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-accent to-accent-light transition-all duration-700"
                      style={{ width: `${l.pct}%` }}
                    />
                  </div>
                </Link>
              ))}
              {(data?.languages ?? []).length === 0 && (
                <p className="py-6 text-center text-xs text-slate-500">No posts in this window.</p>
              )}
            </div>
          )}
        </GlassCard>
      </div>
    </div>
  );
}
