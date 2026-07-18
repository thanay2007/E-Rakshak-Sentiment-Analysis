import { gsap } from "gsap";
import {
  Activity, AlertOctagon, Radio, ShieldAlert, Target, TrendingUp as TrendIcon,
} from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { LanguageChip, ThreatBadge } from "../components/Badges";
import DetailDrawer from "../components/DetailDrawer";
import FeedItemCard from "../components/FeedItemCard";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import { SkeletonChart, SkeletonRow, SkeletonTile } from "../components/Skeletons";
import Sparkline from "../components/Sparkline";
import StatTile from "../components/StatTile";
import { ACCENT, SENTIMENT_COLORS, THREAT_COLORS, THREAT_SHORT } from "../data/constants";
import { useAgo, useLivePosts } from "../hooks/useLive";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import type { Post } from "../services/api";

const TOOLTIP_STYLE = {
  backgroundColor: "rgba(var(--color-base-800), 0.96)",
  border: "1px solid rgba(var(--color-white), 0.1)",
  borderRadius: 12,
  fontSize: 11,
  fontFamily: "'JetBrains Mono', monospace",
  color: "rgb(var(--color-slate-200))",
};

export default function Dashboard() {
  const { data: stats, loading } = usePolling(() => api.stats(), 15000);
  const { data: trends } = usePolling(() => api.trends(24), 60000);
  const livePosts = useLivePosts(30);
  const [initialFeed, setInitialFeed] = useState<Post[]>([]);
  const [selected, setSelected] = useState<Post | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const ago = useAgo(stats?.last_updated);

  useEffect(() => {
    api.feed({ page_size: 12, sort: "recent" }).then((p) => setInitialFeed(p.items)).catch(() => {});
  }, []);

  const feed = useMemo(() => {
    const seen = new Set<string>();
    return [...livePosts, ...initialFeed]
      .filter((p) => (seen.has(p.id) ? false : (seen.add(p.id), true)))
      .slice(0, 14);
  }, [livePosts, initialFeed]);

  // animate the newest live item sliding in from the top
  const newestId = feed[0]?.id;
  useLayoutEffect(() => {
    const el = feedRef.current?.firstElementChild;
    if (!el || !livePosts.length) return;
    gsap.fromTo(el, { y: -26, opacity: 0, scale: 0.985 }, { y: 0, opacity: 1, scale: 1, duration: 0.55, ease: "power3.out" });
  }, [newestId, livePosts.length]);

  const donutData = useMemo(
    () =>
      Object.entries(stats?.threat_distribution ?? {}).map(([name, value]) => ({
        name,
        value,
        fill: THREAT_COLORS[name] ?? "#64748B",
      })),
    [stats]
  );
  const totalDist = donutData.reduce((s, d) => s + d.value, 0) || 1;

  return (
    <div className="space-y-4">
      {/* KPI row */}
      {loading || !stats ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {Array.from({ length: 5 }, (_, i) => <SkeletonTile key={i} />)}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <StatTile label="Posts Monitored" value={stats.kpis.posts_monitored} delta={stats.kpis.posts_monitored_delta} spark={stats.sparklines.posts} icon={Activity} />
          <StatTile label="Active Threats" value={stats.kpis.active_threats} delta={stats.kpis.active_threats_delta} spark={stats.sparklines.threats} color="#EF4444" icon={Target} invertDelta />
          <StatTile label="Critical Alerts" value={stats.kpis.critical_alerts} delta={stats.kpis.critical_alerts_delta} spark={stats.sparklines.alerts} color="#F59E0B" icon={AlertOctagon} invertDelta />
          <StatTile label="Platforms Online" value={stats.kpis.platforms_online} suffix={`/${stats.kpis.platforms_total}`} icon={Radio} color="#10B981" />
          <StatTile label="Coordinated Campaigns" value={stats.kpis.campaigns} color="#A855F7" icon={ShieldAlert} invertDelta />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {/* live feed */}
        <GlassCard className="p-4 xl:col-span-2">
          <SectionTitle
            title="Live Threat Feed"
            sub={`streaming via WebSocket · updated ${ago}`}
            right={<span className="pulse-dot inline-block h-2 w-2 rounded-full bg-threat-neutral text-threat-neutral" aria-label="live" />}
          />
          {feed.length === 0 ? (
            <SkeletonRow n={5} />
          ) : (
            <div ref={feedRef} className="max-h-[520px] space-y-2.5 overflow-y-auto pr-1">
              {feed.map((p) => (
                <FeedItemCard key={p.id} post={p} compact onOpen={setSelected} />
              ))}
            </div>
          )}
        </GlassCard>

        <div className="space-y-4">
          {/* donut */}
          <GlassCard className="p-4">
            <SectionTitle title="Threat Levels" sub="last 24h classification mix" />
            {!stats ? (
              <SkeletonChart h={210} />
            ) : (
              <>
                <ResponsiveContainer width="100%" height={185}>
                  <PieChart>
                    <Pie data={donutData} dataKey="value" nameKey="name" innerRadius={52} outerRadius={80} paddingAngle={2} strokeWidth={2} stroke="#0A0E1A">
                      {donutData.map((d) => (
                        <Cell key={d.name} fill={THREAT_COLORS[d.name] ?? "#64748B"} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: number, n: string) => [`${v} posts`, THREAT_SHORT[n] ?? n]} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="mt-2 space-y-1.5">
                  {donutData.map((d) => (
                    <div key={d.name} className="flex items-center gap-2 text-[11px]">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: THREAT_COLORS[d.name] }} />
                      <span className="text-slate-400">{THREAT_SHORT[d.name] ?? d.name}</span>
                      <span className="ml-auto font-mono text-slate-300">
                        {d.value} · {Math.round((d.value / totalDist) * 100)}%
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </GlassCard>

          {/* trending hashtags */}
          <GlassCard className="p-4">
            <SectionTitle title="Trending Hashtags" sub="spike detection (z-score)" />
            {!trends ? (
              <SkeletonChart h={180} />
            ) : (
              <div className="space-y-2">
                {trends.hashtags.slice(0, 6).map((h) => (
                  <div key={h.term} className="flex items-center gap-2.5 text-xs">
                    <span className="w-28 truncate font-medium text-accent/90">#{h.term}</span>
                    <Sparkline data={h.series} color={h.spiking ? "#EF4444" : ACCENT} width={70} height={20} />
                    <span className="ml-auto font-mono text-slate-400">{h.count}</span>
                    {h.spiking ? (
                      <span className="inline-flex animate-pulse-slow items-center gap-0.5 rounded-md bg-threat-critical/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-threat-critical">
                        <TrendIcon size={9} /> {h.spike_z}σ
                      </span>
                    ) : (
                      <span className={`font-mono text-[10px] ${h.change_pct >= 0 ? "text-threat-neutral" : "text-slate-600"}`}>
                        {h.change_pct >= 0 ? "+" : ""}{h.change_pct}%
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </GlassCard>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {/* sentiment area */}
        <GlassCard className="p-4 xl:col-span-2">
          <SectionTitle title="Sentiment — last 24h" sub="posts per hour by sentiment" />
          {!stats ? (
            <SkeletonChart h={240} />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={stats.sentiment_24h} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
                <defs>
                  {Object.entries(SENTIMENT_COLORS).map(([k, c]) => (
                    <linearGradient key={k} id={`grad-${k}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={c} stopOpacity={0.35} />
                      <stop offset="100%" stopColor={c} stopOpacity={0.02} />
                    </linearGradient>
                  ))}
                </defs>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="hour" tickLine={false} axisLine={false} interval={3} />
                <YAxis tickLine={false} axisLine={false} width={46} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={7} />
                <Area type="monotone" dataKey="negative" stroke={SENTIMENT_COLORS.negative} fill="url(#grad-negative)" strokeWidth={2} />
                <Area type="monotone" dataKey="neutral" stroke={SENTIMENT_COLORS.neutral} fill="url(#grad-neutral)" strokeWidth={2} />
                <Area type="monotone" dataKey="positive" stroke={SENTIMENT_COLORS.positive} fill="url(#grad-positive)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </GlassCard>

        {/* platform bars + accuracy */}
        <div className="space-y-4">
          <GlassCard className="p-4">
            <SectionTitle title="Platform Activity" sub="posts vs threats, 24h" />
            {!stats ? (
              <SkeletonChart h={170} />
            ) : (
              <ResponsiveContainer width="100%" height={170}>
                <BarChart data={stats.platform_activity} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="platform" tickLine={false} axisLine={false} />
                  <YAxis tickLine={false} axisLine={false} width={44} allowDecimals={false} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={7} />
                  <Bar dataKey="posts" fill={ACCENT} radius={[4, 4, 0, 0]} maxBarSize={22} />
                  <Bar dataKey="threats" fill="#EF4444" radius={[4, 4, 0, 0]} maxBarSize={22} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </GlassCard>

          {stats?.accuracy.overall != null && (
            <GlassCard className="p-4">
              <SectionTitle title="Live Model Accuracy" sub={`vs ground truth · n=${stats.accuracy.sample}`} />
              <div className="flex items-end gap-2">
                <span className="font-mono text-3xl font-bold text-threat-neutral">
                  {stats.accuracy.overall}%
                </span>
                <span className="pb-1 text-[10px] text-slate-500">classification accuracy (24h)</span>
              </div>
              <div className="mt-2 space-y-1">
                {Object.entries(stats.accuracy.per_class).map(([label, pct]) => (
                  <div key={label} className="flex items-center gap-2 text-[10.5px]">
                    <span className="w-24 text-slate-500">{THREAT_SHORT[label] ?? label}</span>
                    <div className="h-1 flex-1 rounded-full bg-white/[0.06]">
                      <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: THREAT_COLORS[label] }} />
                    </div>
                    <span className="font-mono text-slate-400">{pct}%</span>
                  </div>
                ))}
              </div>
            </GlassCard>
          )}
        </div>
      </div>

      {/* language strip */}
      {trends && (
        <GlassCard className="flex flex-wrap items-center gap-3 p-3.5">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
            Language mix (24h)
          </span>
          {trends.languages.map((l) => (
            <span key={l.name} className="flex items-center gap-1.5">
              <LanguageChip language={l.name} />
              <span className="font-mono text-[11px] text-slate-400">{l.pct}%</span>
            </span>
          ))}
          <span className="ml-auto font-mono text-[10px] text-slate-600">
            {trends.total_posts} posts analyzed
          </span>
        </GlassCard>
      )}

      <DetailDrawer post={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
