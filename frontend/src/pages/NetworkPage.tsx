import {
  Bot, Download, ExternalLink, Eye, FileSearch, Radar, RotateCcw, Search,
  Share2, Users,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { BotChip, PlatformIcon, SentimentBadge } from "../components/Badges";
import { usePostDetail } from "../components/PostDetailProvider";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import NetworkGraph from "../components/NetworkGraph";
import { SkeletonChart, SkeletonRow } from "../components/Skeletons";
import { concernColor } from "../data/constants";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { useUrlFilters } from "../hooks/useUrlFilters";
import { api } from "../services/api";
import type { NetLink, NetNode } from "../services/api";
import { safeHref } from "../lib/safeUrl";

const WINDOWS = [
  { label: "24 Hours", hours: 24 },
  { label: "48 Hours", hours: 48 },
  { label: "7 Days", hours: 168 },
];

function profileUrl(n: NetNode): string | null {
  if (n.platform === "X") return `https://x.com/${n.id}`;
  if (n.platform === "Reddit") return `https://reddit.com/user/${n.id}`;
  if (n.platform === "Facebook") return `https://facebook.com/${n.id}`;
  if (n.platform === "Instagram") return `https://instagram.com/${n.id}`;
  if (n.platform === "Telegram") return `https://t.me/${n.id}`;
  if (n.platform === "YouTube")
    return `https://www.youtube.com/results?search_query=${encodeURIComponent(n.id)}`;
  return null;
}

const PLATFORMS = ["All", "X", "Reddit", "Facebook", "Instagram", "Telegram", "YouTube"];

/** Connected components over the filtered graph.
 *
 *  Reported because it is the first thing a link analyst reads off a graph:
 *  one large component means a conversation, thirty small ones mean thirty
 *  unrelated conversations that happen to share a time window. Union-find
 *  rather than a traversal so it stays linear in the number of edges. */
function components(nodes: NetNode[], links: NetLink[]): { count: number; largest: number } {
  const parent = new Map<string, string>();
  const find = (x: string): string => {
    let root = x;
    while (parent.get(root) !== root) root = parent.get(root) ?? root;
    while (parent.get(x) !== root) { const next = parent.get(x) ?? root; parent.set(x, root); x = next; }
    return root;
  };
  nodes.forEach((n) => parent.set(n.id, n.id));
  for (const l of links) {
    if (!parent.has(l.source) || !parent.has(l.target)) continue;
    const a = find(l.source), b = find(l.target);
    if (a !== b) parent.set(b, a);
  }
  const sizes = new Map<string, number>();
  nodes.forEach((n) => {
    const root = find(n.id);
    sizes.set(root, (sizes.get(root) ?? 0) + 1);
  });
  return {
    count: sizes.size,
    largest: sizes.size ? Math.max(...sizes.values()) : 0,
  };
}

function downloadText(name: string, mime: string, body: string) {
  const url = URL.createObjectURL(new Blob([body], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export default function NetworkPage() {
  const { openPostId } = usePostDetail();
  // URL-backed so the assistant can open this page already scoped to a window
  // and a platform.
  const { get, getNumber, set } = useUrlFilters();
  const hours = getNumber("hours", 24);
  const setHours = (value: number) => set("hours", value);
  const platform = get("platform", "All") || "All";
  const setPlatform = (value: string) => set("platform", value === "All" ? "" : value);
  const [selected, setSelected] = useState<NetNode | null>(null);
  const { data, loading } = usePolling(
    () => api.network(hours, platform === "All" ? "" : platform),
    60000,
    [hours, platform]
  );
  const revealRef = useGsapReveal<HTMLDivElement>(data?.clusters.length ?? 0);
  const counts = data?.platform_counts ?? {};

  // ── graph-level filters, applied client-side ────────────────────────────
  // The server returns the window; narrowing it is an analyst gesture and
  // should not cost a round trip, so the whole graph is filtered here and the
  // edge list is re-derived to match. Keeping an edge whose endpoint has been
  // filtered out would draw a line to nothing.
  const [query, setQuery] = useState("");
  const [botsOnly, setBotsOnly] = useState(false);
  const [minThreat, setMinThreat] = useState(0);
  /** Handles added to the watchlist in this session — the button reflects it
   *  immediately rather than waiting on the next watchlist poll. */
  const [watched, setWatched] = useState<string[]>([]);

  const view = useMemo(() => {
    const all = data?.nodes ?? [];
    const q = query.trim().toLowerCase();
    const nodes = all.filter(
      (n) =>
        (!botsOnly || n.is_bot) &&
        n.threat >= minThreat &&
        (!q || n.id.toLowerCase().includes(q) || n.label.toLowerCase().includes(q))
    );
    const ids = new Set(nodes.map((n) => n.id));
    const links = (data?.links ?? []).filter((l) => ids.has(l.source) && ids.has(l.target));
    return { nodes, links };
  }, [data, query, botsOnly, minThreat]);

  const filtered = Boolean(query.trim() || botsOnly || minThreat > 0);
  const botCount = view.nodes.filter((n) => n.is_bot).length;
  const comp = useMemo(() => components(view.nodes, view.links), [view]);
  // Undirected density: edges ÷ the number possible between these nodes.
  const density = view.nodes.length > 1
    ? (2 * view.links.length) / (view.nodes.length * (view.nodes.length - 1))
    : 0;

  const topInfluencers = useMemo(
    () => [...view.nodes].sort((a, b) => b.influence - a.influence || b.threat - a.threat).slice(0, 8),
    [view]
  );
  const connections = useMemo(() => {
    if (!selected) return [];
    const ids = new Set<string>();
    for (const l of view.links) {
      if (l.source === selected.id) ids.add(l.target);
      if (l.target === selected.id) ids.add(l.source);
    }
    return view.nodes.filter((n) => ids.has(n.id));
  }, [selected, view]);

  const exportCsv = () => {
    const rows = [["handle", "platform", "followers", "posts", "avg_concern", "centrality", "bot", "cluster"]];
    for (const n of view.nodes) {
      rows.push([n.id, n.platform, String(n.followers), String(n.posts),
        String(Math.round(n.threat)), n.influence.toFixed(4), String(n.is_bot), n.cluster ?? ""]);
    }
    downloadText(`network_${hours}h.csv`, "text/csv",
      rows.map((r) => r.map((c) => `"${c.replace(/"/g, '""')}"`).join(",")).join("\n"));
  };

  const exportJson = () =>
    downloadText(`network_${hours}h.json`, "application/json",
      JSON.stringify({ window_hours: hours, platform, ...view, clusters: data?.clusters ?? [] }, null, 2));

  const stats: [string, string | number, string][] = [
    ["Accounts in view", view.nodes.length, filtered ? `of ${data?.nodes.length ?? 0} in window` : "In interaction graph"],
    ["Interaction links", view.links.length, `density ${(density * 100).toFixed(1)}%`],
    ["Separate components", comp.count, `largest holds ${comp.largest} accounts`],
    ["Bot-like accounts", botCount, view.nodes.length ? `${Math.round((botCount / view.nodes.length) * 100)}% of the graph` : "—"],
  ];

  return (
    <div className="space-y-4">
      {/* Executive Command Header */}
      <div className="flex flex-col gap-3 rounded-2xl border border-white/[0.08] bg-base-950/80 p-4 shadow-xl backdrop-blur-xl md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-accent/40 bg-accent/15 text-accent shadow-[0_0_15px_rgba(20,184,196,0.25)]">
            <Share2 size={20} />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-white sm:text-base">
              Social Network Map & Key Accounts
            </h1>
            <p className="text-xs text-slate-400">
              Who is connected to whom · Which accounts drive the conversation · Which groups post together
            </p>
          </div>
        </div>

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

      {/* Per-Platform Filter Tabs */}
      <div className="flex flex-wrap items-center gap-2">
        {PLATFORMS.map((p) => {
          const n = p === "All"
            ? Object.values(counts).reduce((a, b) => a + b, 0)
            : counts[p] ?? 0;
          const active = platform === p;
          return (
            <button
              key={p}
              onClick={() => { setPlatform(p); setSelected(null); }}
              className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold transition-all ${
                active
                  ? "border-accent/60 bg-accent/15 text-accent shadow-sm"
                  : "border-white/[0.08] bg-white/[0.03] text-slate-400 hover:border-white/20 hover:text-slate-200"
              }`}
            >
              {p !== "All" && <PlatformIcon platform={p} size={15} />}
              <span>{p}</span>
              <span className={`rounded-md px-1.5 py-0.2 font-mono text-[10px] font-bold ${active ? "bg-accent/25 text-accent" : "bg-white/[0.06] text-slate-400"}`}>
                {n}
              </span>
            </button>
          );
        })}
      </div>

      {/* KPI Stats Row */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map(([label, value, sub]) => (
          <GlassCard key={label} className="p-3.5 border border-white/[0.08]">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</div>
            <div className="mt-1 font-mono text-2xl font-black text-slate-100">{value}</div>
            <div className="mt-0.5 text-[11px] text-slate-500">{sub}</div>
          </GlassCard>
        ))}
      </div>

      {/* Main Network Graph & Entity Profile Side Deck */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <GlassCard className="border border-white/[0.08] p-2 xl:col-span-2">
          {/* Graph toolbar — search, narrow, export. Filtering a graph is the
              core analyst gesture; without it a 400-node canvas is a picture
              rather than a tool. */}
          <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.06] px-1.5 pb-2">
            <div className="relative">
              <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="find handle…"
                className="w-40 rounded-lg border border-white/[0.1] bg-white/[0.04] py-1.5 pl-7 pr-2 text-[11px] text-slate-100 placeholder:text-slate-600 focus:border-accent/60 focus:outline-none"
              />
            </div>

            <button
              onClick={() => setBotsOnly((v) => !v)}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] font-bold transition-all ${
                botsOnly
                  ? "border-threat-critical/50 bg-threat-critical/15 text-threat-critical"
                  : "border-white/[0.1] bg-white/[0.03] text-slate-400 hover:text-slate-200"
              }`}
            >
              <Bot size={12} /> Bots only
            </button>

            <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
              min concern
              <input
                type="range" min={0} max={80} step={5} value={minThreat}
                onChange={(e) => setMinThreat(Number(e.target.value))}
                className="w-20 accent-[#14B8C4]"
              />
              <span className="w-5 font-mono text-slate-200">{minThreat}</span>
            </label>

            {filtered && (
              <button
                onClick={() => { setQuery(""); setBotsOnly(false); setMinThreat(0); setSelected(null); }}
                className="inline-flex items-center gap-1 rounded-lg border border-white/[0.1] bg-white/[0.03] px-2 py-1.5 text-[11px] font-semibold text-slate-400 hover:text-accent"
              >
                <RotateCcw size={11} /> Reset
              </button>
            )}

            <div className="ml-auto flex items-center gap-1.5">
              <button onClick={exportCsv} title="Export the accounts in view as CSV"
                className="inline-flex items-center gap-1 rounded-lg border border-white/[0.1] bg-white/[0.03] px-2 py-1.5 text-[11px] font-semibold text-slate-400 hover:text-accent">
                <Download size={11} /> CSV
              </button>
              <button onClick={exportJson} title="Export nodes, links and clusters as JSON"
                className="inline-flex items-center gap-1 rounded-lg border border-white/[0.1] bg-white/[0.03] px-2 py-1.5 text-[11px] font-semibold text-slate-400 hover:text-accent">
                <Download size={11} /> JSON
              </button>
            </div>
          </div>

          {loading && !data ? (
            <SkeletonChart h={600} />
          ) : view.nodes.length === 0 ? (
            <div className="grid h-[600px] place-items-center px-6 text-center">
              <div>
                <Share2 size={26} className="mx-auto mb-2 text-slate-700" />
                <p className="text-sm text-slate-400">
                  {filtered ? "No accounts match these filters." : "No interaction graph in this window."}
                </p>
                <p className="mt-1 text-xs text-slate-600">
                  {filtered
                    ? "Widen the concern floor or clear the handle search."
                    : "Accounts appear here once they share hashtags or post near-identical text."}
                </p>
              </div>
            </div>
          ) : (
            <NetworkGraph
              nodes={view.nodes}
              links={view.links}
              focusId={selected?.id ?? null}
              onSelect={setSelected}
            />
          )}

          {/* Legend. Node size, colour and ring all encode something; a graph
              that does not say what, is decoration. */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-white/[0.06] px-2 pt-2 text-[10px] text-slate-500">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-slate-500" />
              <span className="h-1.5 w-1.5 rounded-full bg-slate-500" />
              size = degree centrality
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: concernColor(10) }} />
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: concernColor(75) }} />
              colour = average concern
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full border border-dashed border-threat-critical" />
              dashed ring = bot-like account
            </span>
            <span>solid edge = near-identical text · faint edge = shared hashtag</span>
            {data && (
              <span className="ml-auto font-mono">
                {view.nodes.length} nodes · {view.links.length} edges · {hours}h window
              </span>
            )}
          </div>
        </GlassCard>

        <div className="space-y-4">
          {/* Entity profile */}
          {selected ? (
            <GlassCard className="border border-accent/40 bg-accent/[0.02] p-4 shadow-lg">
              <SectionTitle title="Entity Profile" right={<Users size={15} className="text-accent" />} />
              <div className="mt-3 flex items-center gap-3">
                <PlatformIcon platform={selected.platform} size={32} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-bold text-slate-100">{selected.label}</span>
                    {selected.is_bot && <BotChip />}
                  </div>
                  <div className="font-mono text-xs text-slate-400">
                    @{selected.id} · {selected.followers.toLocaleString()} followers
                  </div>
                </div>
                {profileUrl(selected) && (
                  <a
                    href={safeHref(profileUrl(selected))}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-xl border border-white/10 bg-white/[0.04] p-2 text-slate-300 hover:bg-white/[0.08] hover:text-accent transition-all"
                    title="Open live profile"
                  >
                    <ExternalLink size={14} />
                  </a>
                )}
              </div>

              <div className="mt-3.5 grid grid-cols-3 gap-2 text-center">
                {[
                  ["Avg Threat", Math.round(selected.threat)],
                  ["Posts", selected.posts],
                  ["Centrality", (selected.influence * 100).toFixed(1)],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-xl border border-white/[0.06] bg-base-950/70 p-2.5">
                    <div
                      className="font-mono text-base font-black"
                      style={{ color: k === "Avg Concern" ? concernColor(selected.threat) : "#E2E8F0" }}
                    >
                      {v}
                    </div>
                    <div className="text-[9.5px] font-bold uppercase tracking-wider text-slate-400">{k}</div>
                  </div>
                ))}
              </div>

              {selected.cluster && (
                <div className="mt-3 rounded-xl border border-threat-critical/40 bg-threat-critical/10 p-2.5 font-mono text-xs font-bold text-threat-critical">
                  ⚠ Member of coordinated cluster: {selected.cluster}
                </div>
              )}

              {/* Pivots. A selected entity that cannot be taken anywhere is a
                  readout; these are the three places an analyst goes next. */}
              <div className="mt-3 grid grid-cols-3 gap-1.5">
                <Link
                  to={`/app/feed?q=${encodeURIComponent(selected.id)}`}
                  className="inline-flex items-center justify-center gap-1 rounded-xl border border-white/[0.1] bg-white/[0.04] px-2 py-1.5 text-[10.5px] font-bold text-slate-300 transition-all hover:border-accent/40 hover:text-accent"
                >
                  <FileSearch size={11} /> Posts
                </Link>
                <Link
                  to={`/app/investigate?tab=username&u=${encodeURIComponent(selected.id)}`}
                  className="inline-flex items-center justify-center gap-1 rounded-xl border border-white/[0.1] bg-white/[0.04] px-2 py-1.5 text-[10.5px] font-bold text-slate-300 transition-all hover:border-accent/40 hover:text-accent"
                >
                  <Radar size={11} /> Trace
                </Link>
                <button
                  onClick={async () => {
                    await api.addWatch({
                      kind: "account", value: selected.id, priority: "high",
                      note: `Added from network graph — centrality ${(selected.influence * 100).toFixed(1)}, avg concern ${Math.round(selected.threat)}`,
                    });
                    setWatched((w) => [...w, selected.id]);
                  }}
                  disabled={watched.includes(selected.id)}
                  className="inline-flex items-center justify-center gap-1 rounded-xl border border-white/[0.1] bg-white/[0.04] px-2 py-1.5 text-[10.5px] font-bold text-slate-300 transition-all hover:border-accent/40 hover:text-accent disabled:opacity-50"
                >
                  <Eye size={11} /> {watched.includes(selected.id) ? "Watched" : "Watch"}
                </button>
              </div>

              {connections.length > 0 && (
                <div className="mt-3.5">
                  <div className="mb-1.5 text-[10.5px] font-bold uppercase tracking-wider text-slate-400">
                    Linked Graph Nodes ({connections.length})
                  </div>
                  <div className="flex max-h-28 flex-wrap gap-1.5 overflow-y-auto">
                    {connections.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => setSelected(c)}
                        className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 font-mono text-[10.5px] text-slate-300 hover:border-accent/40 hover:bg-accent/10 hover:text-accent transition-all"
                      >
                        @{c.id}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </GlassCard>
          ) : (
            <GlassCard className="p-6 border border-white/[0.08] text-center">
              <SectionTitle title="Entity Profile" right={<Users size={15} className="text-slate-500" />} />
              <p className="mt-4 text-xs text-slate-400">
                Click any node on the force graph or influencer roster to inspect account forensics.
              </p>
            </GlassCard>
          )}

          {/* Influence roster */}
          <GlassCard className="p-4 border border-white/[0.08]">
            <SectionTitle
              title="Most Influential Accounts"
              sub="Most connected accounts first"
              right={<Radar size={15} className="text-accent" />}
            />
            {loading && !data ? (
              <SkeletonRow n={5} />
            ) : (
              <div className="mt-3 space-y-1.5">
                {topInfluencers.map((n, i) => (
                  <button
                    key={n.id}
                    onClick={() => setSelected(n)}
                    className={`flex w-full items-center gap-2.5 rounded-xl border border-transparent p-2 text-left transition-all hover:border-white/10 hover:bg-white/[0.04] ${
                      selected?.id === n.id ? "border-accent/40 bg-accent/10" : ""
                    }`}
                  >
                    <span className="w-4 font-mono text-xs font-bold text-slate-400">#{i + 1}</span>
                    <PlatformIcon platform={n.platform} size={18} />
                    <span className="min-w-0 flex-1 truncate font-mono text-xs font-semibold text-slate-200">
                      @{n.id}
                    </span>
                    {n.is_bot && <span className="font-mono text-[9.5px] font-bold text-threat-critical">BOT</span>}
                    <span className="font-mono text-xs font-bold" style={{ color: concernColor(n.threat) }}>
                      {Math.round(n.threat)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </GlassCard>
        </div>
      </div>

      {/* Coordinated Clusters */}
      <GlassCard className="p-4 border border-white/[0.08]">
        <SectionTitle
          title="Groups Posting Together"
          sub={data ? `${data.clusters.length} groups of accounts posting the same thing at the same time` : undefined}
          right={<Bot size={16} className="text-threat-critical" />}
        />
        {loading && !data ? (
          <SkeletonRow n={2} />
        ) : (
          <div ref={revealRef} className="mt-3.5 grid grid-cols-1 gap-3.5 lg:grid-cols-2">
            {data?.clusters.map((c) => (
              <div
                key={c.id}
                className="reveal-item rounded-xl border border-threat-critical/30 bg-threat-critical/[0.03] p-4 shadow-sm"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-black text-threat-critical">{c.id}</span>
                  <SentimentBadge label={c.label} />
                  <span className="font-mono text-xs text-slate-400">
                    {c.accounts.length} accounts · {c.posts} posts
                  </span>
                  <span className="ml-auto font-mono text-xs font-bold text-accent">
                    {(c.confidence * 100).toFixed(0)}% Match
                  </span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.08]">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-threat-inflammatory to-threat-critical"
                    style={{ width: `${c.confidence * 100}%` }}
                  />
                </div>
                <ul className="mt-2.5 space-y-1 text-xs text-slate-300">
                  {c.why.map((w, i) => (
                    <li key={i} className="flex items-start gap-1.5">
                      <span className="text-threat-critical font-bold">▸</span>
                      <span>{w}</span>
                    </li>
                  ))}
                </ul>
                {c.sample_post_id ? (
                  <button
                    onClick={() => openPostId(c.sample_post_id!)}
                    className="mt-2.5 block w-full rounded-xl border border-white/[0.06] bg-base-950/70 p-2.5 text-left text-xs italic text-slate-300 transition-colors hover:border-accent/40 hover:bg-white/[0.04]"
                  >
                    <span className="line-clamp-2">“{c.sample_text}”</span>
                    <span className="mt-1 block not-italic text-[10.5px] font-semibold text-accent">
                      open this post →
                    </span>
                  </button>
                ) : (
                  <p className="mt-2.5 line-clamp-2 rounded-xl border border-white/[0.06] bg-base-950/70 p-2.5 text-xs italic text-slate-300">
                    “{c.sample_text}”
                  </p>
                )}
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {c.accounts.slice(0, 8).map((a) => (
                    <span key={a} className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 font-mono text-[10.5px] text-slate-300">
                      @{a}
                    </span>
                  ))}
                  {c.accounts.length > 8 && (
                    <span className="font-mono text-[10.5px] text-slate-500">+{c.accounts.length - 8} more</span>
                  )}
                </div>
              </div>
            ))}
            {data?.clusters.length === 0 && (
              <p className="col-span-full py-8 text-center text-xs text-slate-400">
                No coordinated swarms detected in this time window.
              </p>
            )}
          </div>
        )}
      </GlassCard>
    </div>
  );
}
