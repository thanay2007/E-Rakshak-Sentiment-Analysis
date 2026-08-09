import { gsap } from "gsap";
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Cpu,
  Download,
  HelpCircle,
  Radio,
  RefreshCw,
  Search,
  ShieldAlert,
  Target,
  TrendingUp as TrendIcon,
} from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import DetailDrawer from "../components/DetailDrawer";
import EmergingPanel from "../components/EmergingPanel";
import FeedItemCard from "../components/FeedItemCard";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import { Logo } from "../components/Sidebar";
import { SkeletonChart, SkeletonTile } from "../components/Skeletons";
import Sparkline from "../components/Sparkline";
import StatTile from "../components/StatTile";
import { ACCENT, SENTIMENT_COLORS, THREAT_COLORS, THREAT_SHORT } from "../data/constants";
import { useAgo, useLivePosts } from "../hooks/useLive";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import type { Post } from "../services/api";

const TOOLTIP_STYLE = {
  backgroundColor: "rgba(10, 15, 30, 0.98)",
  border: "1px solid rgba(255, 255, 255, 0.18)",
  borderRadius: 14,
  fontSize: 12,
  fontFamily: "'JetBrains Mono', monospace",
  color: "#F8FAFC",
  padding: "10px 14px",
  boxShadow: "0 15px 35px -5px rgba(0, 0, 0, 0.7)",
};

const THREAT_DESCRIPTIONS: Record<string, string> = {
  "Incitement to Violence": "Immediate threat to public order & safety",
  Inflammatory: "Communal tension, hate speech & hostile rhetoric",
  "Fake News": "Disinformation, manipulated media & hoaxes",
  Neutral: "Public discourse, factual reporting & queries",
};

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: stats, error: statsError, loading, refresh: refreshStats } = usePolling(() => api.stats(), 15000);
  const { data: trends, error: trendsError } = usePolling(() => api.trends(24), 60000);
  const livePosts = useLivePosts(30);
  const [initialFeed, setInitialFeed] = useState<Post[]>([]);
  const [selected, setSelected] = useState<Post | null>(null);
  const [feedThreatFilter, setFeedThreatFilter] = useState<string>("all");
  const feedRef = useRef<HTMLDivElement>(null);
  const ago = useAgo(stats?.last_updated);

  useEffect(() => {
    api.feed({ page_size: 16, sort: "recent" }).then((p) => setInitialFeed(p.items)).catch(() => {});
  }, []);

  const rawFeed = useMemo(() => {
    const seen = new Set<string>();
    return [...livePosts, ...initialFeed]
      .filter((p) => (seen.has(p.id) ? false : (seen.add(p.id), true)))
      .slice(0, 24);
  }, [livePosts, initialFeed]);

  const filteredFeed = useMemo(() => {
    if (feedThreatFilter === "all") return rawFeed.slice(0, 14);
    return rawFeed.filter((p) => p.threat_label === feedThreatFilter).slice(0, 14);
  }, [rawFeed, feedThreatFilter]);

  // animate the newest live item sliding in from the top
  const newestId = filteredFeed[0]?.id;
  useLayoutEffect(() => {
    const el = feedRef.current?.firstElementChild;
    if (!el || !livePosts.length) return;
    gsap.fromTo(
      el,
      { y: -24, opacity: 0, scale: 0.98 },
      { y: 0, opacity: 1, scale: 1, duration: 0.5, ease: "power3.out" }
    );
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

  // Filter counts for quick badges
  const filterCounts = useMemo(() => {
    const counts: Record<string, number> = { all: rawFeed.length };
    rawFeed.forEach((p) => {
      counts[p.threat_label] = (counts[p.threat_label] || 0) + 1;
    });
    return counts;
  }, [rawFeed]);

  const [isSyncing, setIsSyncing] = useState(false);

  const handleSync = async () => {
    setIsSyncing(true);
    try {
      await Promise.all([
        refreshStats(),
        api.feed({ page_size: 16, sort: "recent" }).then((p) => setInitialFeed(p.items)).catch(() => {}),
      ]);
    } finally {
      setTimeout(() => setIsSyncing(false), 750);
    }
  };

  return (
    <div className="space-y-4">
      {/* ── Executive Command Header ───────────────────────────────────── */}
      <div className="flex flex-col gap-3 rounded-2xl border border-white/[0.08] bg-base-950/80 px-5 py-3.5 shadow-xl backdrop-blur-xl md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-accent/40 bg-accent/15 text-accent shadow-[0_0_15px_rgba(245,158,11,0.25)]">
            <Logo size={24} />
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-sm font-black tracking-wide text-white uppercase sm:text-base">
              State Cyber Defense Intelligence Hub
            </h1>
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" /> LIVE TELEMETRY
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleSync}
            disabled={isSyncing}
            className={`inline-flex items-center gap-2 rounded-xl border px-3.5 py-1.5 text-xs font-semibold transition-all duration-200 ${
              isSyncing || loading
                ? "border-accent/60 bg-accent/20 text-accent shadow-[0_0_15px_rgba(245,158,11,0.25)]"
                : "border-white/10 bg-white/[0.04] text-slate-300 hover:border-accent/40 hover:bg-white/[0.08] hover:text-white"
            }`}
            title="Synchronize telemetry and feed"
          >
            <RefreshCw
              size={13}
              className={`${
                isSyncing || loading
                  ? "animate-spin text-accent"
                  : "text-slate-400 group-hover:text-slate-200"
              }`}
            />
            <span className="font-mono text-xs">
              {isSyncing ? "Syncing…" : "Sync"}
            </span>
          </button>
        </div>
      </div>

      {statsError && !stats && (
        <GlassCard className="space-y-3 p-4 text-sm text-slate-200 border-red-500/30 bg-red-500/10">
          <div className="font-semibold text-red-300 flex items-center gap-2">
            <AlertOctagon size={16} /> Could not load dashboard telemetry
          </div>
          <div className="text-xs text-slate-400">{statsError}</div>
          <button
            onClick={() => void refreshStats()}
            className="rounded-xl border border-accent/40 bg-accent/15 px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent/25"
          >
            Retry Sync
          </button>
        </GlassCard>
      )}

      {/* ── Top Row: 5 Core Operational KPIs ─────────────────────────── */}
      {loading || !stats ? (
        <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-5">
          {Array.from({ length: 5 }, (_, i) => (
            <SkeletonTile key={i} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-5">
          <StatTile
            label="Posts Monitored"
            value={stats.kpis.posts_monitored}
            delta={stats.kpis.posts_monitored_delta}
            spark={stats.sparklines.posts}
            icon={Activity}
            color="#38BDF8"
            tooltip="Total social media posts evaluated by NLP pipeline in the last 24h."
          />
          <StatTile
            label="Active Threats"
            value={stats.kpis.active_threats}
            delta={stats.kpis.active_threats_delta}
            spark={stats.sparklines.threats}
            color="#EF4444"
            icon={Target}
            invertDelta
            tooltip="Flagged as Incitement to Violence, Inflammatory Hate Speech, or Fake News."
          />
          <StatTile
            label="Critical Incidents"
            value={stats.kpis.critical_alerts}
            delta={stats.kpis.critical_alerts_delta}
            spark={stats.sparklines.alerts}
            color="#F59E0B"
            icon={AlertOctagon}
            invertDelta
            tooltip="Severe incidents escalated for law enforcement intervention."
          />
          <StatTile
            label="Platforms Online"
            value={stats.kpis.platforms_online}
            suffix={`/${stats.kpis.platforms_total}`}
            icon={Radio}
            color="#10B981"
            tooltip="Active social media pipelines (X, Telegram, Reddit, Facebook, Instagram, YouTube)."
          />
          <StatTile
            label="Bot Swarm Campaigns"
            value={stats.kpis.campaigns}
            color="#A855F7"
            icon={Bot}
            invertDelta
            tooltip="Synchronized inauthentic account clusters spreading manufactured outrage."
          />
        </div>
      )}

      {/* ── Main Section: Live Feed + Threat Breakdown & Hashtag Surge ── */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {/* Left 2 Cols: Live Threat Stream (Fixed proportional height) */}
        <GlassCard className="flex flex-col p-4 xl:col-span-2 h-[620px]">
          <div className="mb-3 flex flex-col gap-2.5 border-b border-white/[0.08] pb-3 sm:flex-row sm:items-center sm:justify-between shrink-0">
            <div className="shrink-0 min-w-0">
              <div className="flex items-center gap-2">
                <Radio size={16} className="text-emerald-400 shrink-0" />
                <h2 className="text-sm font-extrabold uppercase tracking-wider text-white whitespace-nowrap">
                  Live OSINT Threat Stream
                </h2>
              </div>
              <p className="text-[11px] text-slate-400 mt-0.5">
                Real-time multi-platform intelligence ingestion & automated threat scoring
              </p>
            </div>

            {/* Quick Filter Pill Buttons */}
            <div className="flex flex-wrap items-center gap-1.5">
              {[
                { id: "all", label: "All Feeds", color: "#38BDF8" },
                { id: "Incitement to Violence", label: "Violence", color: "#DC2626" },
                { id: "Inflammatory", label: "Inflammatory", color: "#EA580C" },
                { id: "Fake News", label: "Fake News", color: "#9333EA" },
                { id: "Neutral", label: "Neutral", color: "#059669" },
              ].map(({ id, label, color }) => {
                const isSelected = feedThreatFilter === id;
                const count = id === "all" ? rawFeed.length : (filterCounts[id] ?? 0);
                return (
                  <button
                    key={id}
                    onClick={() => setFeedThreatFilter(id)}
                    className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-xs font-semibold transition-all ${
                      isSelected
                        ? "border-accent bg-accent/20 text-accent shadow-sm"
                        : "border-white/[0.08] bg-white/[0.02] text-slate-400 hover:border-white/20 hover:bg-white/[0.06] hover:text-slate-100"
                    }`}
                  >
                    <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
                    <span>{label}</span>
                    <span className={`font-mono text-[10px] ${isSelected ? "text-accent font-bold" : "text-slate-500"}`}>
                      {count}
                    </span>
                  </button>
                );
              })}

              <Link
                to="/app/feed"
                className="ml-0.5 inline-flex items-center gap-1 rounded-lg border border-accent/40 bg-accent/10 px-2.5 py-1 text-xs font-bold text-accent hover:bg-accent/20 transition-all"
              >
                <span>Full Feed</span> <ArrowUpRight size={12} />
              </Link>
            </div>
          </div>

          {filteredFeed.length === 0 ? (
            <div className="flex flex-1 items-center justify-center text-center text-xs text-slate-400">
              No live posts matching the selected threat filter. Select "All Feeds" to view incoming activity.
            </div>
          ) : (
            <div ref={feedRef} className="flex-1 space-y-2.5 overflow-y-auto pr-1 custom-scrollbar">
              {filteredFeed.map((p) => (
                <FeedItemCard key={p.id} post={p} compact onOpen={setSelected} />
              ))}
            </div>
          )}
        </GlassCard>

        {/* Right 1 Col: Threat Breakdown & Viral Hashtags (Balanced heights) */}
        <div className="flex flex-col gap-4 h-[620px]">
          {/* Threat Breakdown Donut & Interactive List */}
          <GlassCard className="flex flex-1 flex-col justify-between p-4">
            <SectionTitle
              title="Threat Classification"
            />
            {!stats ? (
              <SkeletonChart h={180} />
            ) : (
              <div className="flex flex-col justify-between flex-1 gap-2 pt-1">
                <div className="relative flex items-center justify-center">
                  <ResponsiveContainer width="100%" height={138}>
                    <PieChart>
                      <Pie
                        data={donutData}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={42}
                        outerRadius={65}
                        paddingAngle={3}
                        strokeWidth={2}
                        stroke="#070B16"
                      >
                        {donutData.map((d) => (
                          <Cell key={d.name} fill={THREAT_COLORS[d.name] ?? "#64748B"} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={TOOLTIP_STYLE}
                        formatter={(v: number, n: string) => [`${v.toLocaleString()} posts`, THREAT_SHORT[n] ?? n]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  {/* Center Donut Badge */}
                  <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
                    <span className="font-mono text-base font-black text-white leading-none">
                      {totalDist.toLocaleString()}
                    </span>
                    <span className="text-[9px] font-bold uppercase tracking-wider text-slate-400 mt-0.5">
                      Posts
                    </span>
                  </div>
                </div>

                {/* 2x2 Grid for compact balanced breakdown */}
                <div className="grid grid-cols-2 gap-2">
                  {donutData.map((d) => {
                    const pct = Math.round((d.value / totalDist) * 100);
                    return (
                      <div
                        key={d.name}
                        onClick={() => navigate(`/app/feed?threat=${encodeURIComponent(d.name)}`)}
                        className="group flex cursor-pointer items-center justify-between rounded-xl border border-white/[0.06] bg-white/[0.02] p-2 text-xs transition-all hover:border-accent/40 hover:bg-white/[0.06]"
                        title={`Click to filter threat feed by ${d.name}`}
                      >
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span
                            className="h-2 w-2 rounded-full shrink-0 shadow-sm"
                            style={{ backgroundColor: THREAT_COLORS[d.name] }}
                          />
                          <span className="truncate font-semibold text-slate-200 group-hover:text-white text-[11px]">
                            {THREAT_SHORT[d.name] ?? d.name}
                          </span>
                        </div>
                        <span
                          className="rounded px-1.5 py-0.5 font-mono text-[10px] font-black shrink-0"
                          style={{
                            backgroundColor: `${THREAT_COLORS[d.name]}22`,
                            color: THREAT_COLORS[d.name],
                          }}
                        >
                          {pct}%
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </GlassCard>

          {/* Viral Hashtag Surge Tracker */}
          <GlassCard className="flex flex-1 flex-col justify-between p-4 overflow-hidden">
            <SectionTitle
              title="Viral Hashtags"
            />
            {trendsError && !trends ? (
              <div className="py-4 text-xs text-slate-400">{trendsError}</div>
            ) : !trends ? (
              <SkeletonChart h={140} />
            ) : (
              <div className="space-y-1.5 flex-1 flex flex-col justify-around pt-1">
                {trends.hashtags.slice(0, 4).map((h, i) => (
                  <div
                    key={h.term}
                    onClick={() => navigate(`/app/feed?q=${encodeURIComponent("#" + h.term)}`)}
                    className="flex cursor-pointer items-center justify-between gap-2 rounded-xl border border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5 text-xs transition-all hover:border-accent/40 hover:bg-white/[0.06]"
                    title="Click to search posts containing this hashtag"
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <span className="font-mono text-[10px] text-slate-500 font-bold">#{i + 1}</span>
                      <span className="truncate font-bold text-accent hover:underline text-[11.5px]">
                        #{h.term}
                      </span>
                    </div>
                    <Sparkline data={h.series} color={h.spiking ? "#EF4444" : ACCENT} width={50} height={16} />
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="font-mono text-[10.5px] text-slate-300">
                        {h.count.toLocaleString()}
                      </span>
                      {h.spiking ? (
                        <span className="inline-flex items-center gap-0.5 rounded border border-threat-critical/40 bg-threat-critical/20 px-1 py-0.2 font-mono text-[9.5px] font-black text-threat-critical">
                          <TrendIcon size={9} /> {h.spike_z}σ
                        </span>
                      ) : (
                        <span className={`font-mono text-[9.5px] font-bold ${h.change_pct >= 0 ? "text-emerald-400" : "text-slate-400"}`}>
                          {h.change_pct >= 0 ? "+" : ""}{h.change_pct}%
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </GlassCard>
        </div>
      </div>

      {/* ── Emerging Unverified Rumor Triage Panel ──────────────────── */}
      <EmergingPanel />

      {/* ── Bottom Section: Sentiment Timeline + Platform & Model Accuracy */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {/* Left 2 Cols: Sentiment Polarity Area Timeline */}
        <GlassCard className="flex flex-col justify-between p-5 xl:col-span-2 h-[390px]">
          <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-white/[0.06] pb-3 shrink-0">
            <div>
              <h2 className="text-sm font-extrabold uppercase tracking-wider text-white">
                Sentiment Polarity Velocity Timeline
              </h2>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <span className="inline-flex items-center gap-1.5 font-semibold text-rose-400">
                <span className="h-2 w-2 rounded-full bg-rose-500 shadow-sm" /> Negative / Hostile
              </span>
              <span className="inline-flex items-center gap-1.5 font-semibold text-slate-300">
                <span className="h-2 w-2 rounded-full bg-slate-400 shadow-sm" /> Neutral / Factual
              </span>
              <span className="inline-flex items-center gap-1.5 font-semibold text-emerald-400">
                <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-sm" /> Positive / Constructive
              </span>
            </div>
          </div>

          {!stats ? (
            <SkeletonChart h={280} />
          ) : (
            <div className="flex-1 w-full pt-1">
              <ResponsiveContainer width="100%" height={290}>
                <AreaChart data={stats.sentiment_24h} margin={{ top: 10, right: 15, left: -10, bottom: 0 }}>
                  <defs>
                    {Object.entries(SENTIMENT_COLORS).map(([k, c]) => (
                      <linearGradient key={k} id={`grad-${k}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={c} stopOpacity={0.4} />
                        <stop offset="100%" stopColor={c} stopOpacity={0.02} />
                      </linearGradient>
                    ))}
                  </defs>
                  <CartesianGrid vertical={false} stroke="rgba(255,255,255,0.08)" strokeDasharray="3 3" />
                  <XAxis dataKey="hour" tickLine={false} axisLine={false} interval={3} tick={{ fill: "#94A3B8", fontSize: 11 }} />
                  <YAxis tickLine={false} axisLine={false} width={48} allowDecimals={false} tick={{ fill: "#94A3B8", fontSize: 11 }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Area
                    type="monotone"
                    name="Negative / Hostile"
                    dataKey="negative"
                    stroke={SENTIMENT_COLORS.negative}
                    fill="url(#grad-negative)"
                    strokeWidth={2.5}
                  />
                  <Area
                    type="monotone"
                    name="Neutral / Factual"
                    dataKey="neutral"
                    stroke={SENTIMENT_COLORS.neutral}
                    fill="url(#grad-neutral)"
                    strokeWidth={2.5}
                  />
                  <Area
                    type="monotone"
                    name="Positive / Constructive"
                    dataKey="positive"
                    stroke={SENTIMENT_COLORS.positive}
                    fill="url(#grad-positive)"
                    strokeWidth={2.5}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </GlassCard>

        {/* Right 1 Col: Platform Activity & Model Accuracy (Cleanly split half cards) */}
        <div className="flex flex-col gap-4 h-[390px]">
          {/* Platform Activity Bar Chart (Sideways / Horizontal to cleanly fill card) */}
          <GlassCard className="flex flex-1 flex-col justify-between p-3.5 overflow-hidden">
            <div className="flex items-center justify-between border-b border-white/[0.08] pb-1.5 shrink-0">
              <span className="text-xs font-bold uppercase tracking-wide text-white">
                Platform Threat Ingestion
              </span>
              <div className="flex items-center gap-2.5 text-[10px]">
                <span className="inline-flex items-center gap-1 font-semibold text-slate-300">
                  <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: ACCENT }} /> Posts
                </span>
                <span className="inline-flex items-center gap-1 font-semibold text-rose-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-red-500" /> Threats
                </span>
              </div>
            </div>

            {!stats ? (
              <SkeletonChart h={130} />
            ) : (
              <div className="flex-1 w-full pt-1 min-h-0">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    layout="vertical"
                    data={stats.platform_activity}
                    margin={{ top: 2, right: 10, left: 10, bottom: 2 }}
                    barGap={1}
                    barCategoryGap="16%"
                  >
                    <CartesianGrid horizontal={false} stroke="rgba(255,255,255,0.06)" strokeDasharray="3 3" />
                    <XAxis
                      type="number"
                      tickLine={false}
                      axisLine={false}
                      allowDecimals={false}
                      tick={{ fill: "#94A3B8", fontSize: 9 }}
                    />
                    <YAxis
                      type="category"
                      dataKey="platform"
                      tickLine={false}
                      axisLine={false}
                      width={54}
                      tick={{ fill: "#E2E8F0", fontSize: 9.5, fontWeight: 600 }}
                    />
                    <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "rgba(255,255,255,0.05)" }} />
                    <Bar name="Total Posts" dataKey="posts" fill={ACCENT} radius={[0, 3, 3, 0]} maxBarSize={8} />
                    <Bar name="Threats Flagged" dataKey="threats" fill="#EF4444" radius={[0, 3, 3, 0]} maxBarSize={8} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </GlassCard>

          {/* Model Accuracy Card */}
          {stats?.accuracy.overall != null && (
            <GlassCard className="flex flex-1 flex-col justify-between p-3.5 overflow-hidden">
              <div className="flex items-center justify-between border-b border-white/[0.08] pb-1.5">
                <div className="flex items-center gap-2">
                  <Cpu size={15} className="text-emerald-400" />
                  <span className="text-xs font-bold text-slate-200 uppercase tracking-wide">
                    Transformer NLP Accuracy
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-sm font-black text-emerald-400">
                    {stats.accuracy.overall}%
                  </span>
                  <span className="inline-flex items-center gap-0.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.2 text-[9px] font-bold text-emerald-300">
                    <CheckCircle2 size={9} /> VALIDATED
                  </span>
                </div>
              </div>

              <div className="space-y-1.5 pt-1">
                {Object.entries(stats.accuracy.per_class).map(([label, pct]) => (
                  <div key={label} className="flex items-center gap-2 text-[11px]">
                    <span className="w-24 truncate font-medium text-slate-300">{THREAT_SHORT[label] ?? label}</span>
                    <div className="h-1.5 flex-1 rounded-full bg-white/[0.08]">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{ width: `${pct}%`, backgroundColor: THREAT_COLORS[label] ?? "#64748B" }}
                      />
                    </div>
                    <span className="w-8 text-right font-mono text-[10px] font-bold text-slate-200">
                      {pct}%
                    </span>
                  </div>
                ))}
              </div>
            </GlassCard>
          )}
        </div>
      </div>

      <DetailDrawer post={selected} onClose={() => setSelected(null)} />
    </div>
  );
}



