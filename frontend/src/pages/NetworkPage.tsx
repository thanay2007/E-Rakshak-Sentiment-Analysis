import { ExternalLink, Radar, Share2, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { BotChip, PlatformIcon, SentimentBadge } from "../components/Badges";
import { usePostDetail } from "../components/PostDetailProvider";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import NetworkGraph from "../components/NetworkGraph";
import { SkeletonChart, SkeletonRow } from "../components/Skeletons";
import { concernColor } from "../data/constants";
import { usePolling } from "../hooks/usePolling";
import { useUrlFilters } from "../hooks/useUrlFilters";
import { api } from "../services/api";
import type { NetNode } from "../services/api";
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
  const counts = data?.platform_counts ?? {};

  const botCount = data?.nodes.filter((n) => n.is_bot).length ?? 0;
  const topInfluencers = useMemo(
    () => [...(data?.nodes ?? [])].sort((a, b) => b.influence - a.influence || b.threat - a.threat).slice(0, 8),
    [data]
  );
  const connections = useMemo(() => {
    if (!selected || !data) return [];
    const ids = new Set<string>();
    for (const l of data.links) {
      if (l.source === selected.id) ids.add(l.target);
      if (l.target === selected.id) ids.add(l.source);
    }
    return data.nodes.filter((n) => ids.has(n.id));
  }, [selected, data]);

  const stats: [string, string | number, string][] = [
    ["Accounts Monitored", data?.nodes.length ?? "—", "In interaction graph"],
    ["Interaction Links", data?.links.length ?? "—", "Links between accounts and signs of posting together"],
    ["Bot-Like Accounts", botCount, "Accounts with an automated-activity score above 0.65"],
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
              Account Connections
            </h1>
            <p className="text-xs text-slate-400">
              See connected accounts and possible automated activity
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
              <span className={`rounded-md px-1.5 py-0.2 font-mono text-xs font-bold ${active ? "bg-accent/25 text-accent" : "bg-white/[0.06] text-slate-400"}`}>
                {n}
              </span>
            </button>
          );
        })}
      </div>

      {/* KPI Stats Row */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {stats.map(([label, value, sub]) => (
          <GlassCard key={label} className="p-3.5 border border-white/[0.08]">
            <div className="text-xs font-bold uppercase tracking-wider text-slate-400">{label}</div>
            <div className="mt-1 font-mono text-2xl font-black text-slate-100">{value}</div>
            <div className="mt-0.5 text-[13px] text-slate-500">{sub}</div>
          </GlassCard>
        ))}
      </div>

      {/* Main Network Graph & Account Details Side Deck */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <GlassCard className="p-2 border border-white/[0.08] xl:col-span-2">
          {loading && !data ? (
            <SkeletonChart h={600} />
          ) : data ? (
            <NetworkGraph
              nodes={data.nodes}
              links={data.links}
              focusId={selected?.id ?? null}
              onSelect={setSelected}
            />
          ) : null}
        </GlassCard>

        <div className="space-y-4">
          {/* Entity profile */}
          {selected ? (
            <GlassCard className="border border-accent/40 bg-accent/[0.02] p-4 shadow-lg">
              <SectionTitle title="Account Details" right={<Users size={15} className="text-accent" />} />
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
                  ["Connection score", (selected.influence * 100).toFixed(1)],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-xl border border-white/[0.06] bg-base-950/70 p-2.5">
                    <div
                      className="font-mono text-base font-black"
                      style={{ color: k === "Avg Concern" ? concernColor(selected.threat) : "#E2E8F0" }}
                    >
                      {v}
                    </div>
                    <div className="text-[13px] font-bold uppercase tracking-wider text-slate-400">{k}</div>
                  </div>
                ))}
              </div>

              {selected.cluster && (
                <div className="mt-3 rounded-xl border border-threat-critical/40 bg-threat-critical/10 p-2.5 font-mono text-xs font-bold text-threat-critical">
                  ⚠ Member of coordinated cluster: {selected.cluster}
                </div>
              )}

              {connections.length > 0 && (
                <div className="mt-3.5">
                  <div className="mb-1.5 text-xs font-bold uppercase tracking-wider text-slate-400">
                    Linked Graph Nodes ({connections.length})
                  </div>
                  <div className="flex max-h-28 flex-wrap gap-1.5 overflow-y-auto">
                    {connections.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => setSelected(c)}
                        className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 font-mono text-xs text-slate-300 hover:border-accent/40 hover:bg-accent/10 hover:text-accent transition-all"
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
              <SectionTitle title="Account Details" right={<Users size={15} className="text-slate-500" />} />
              <p className="mt-4 text-xs text-slate-400">
                Click an account in the chart or list to see its details.
              </p>
            </GlassCard>
          )}

          {/* Influence roster */}
          <GlassCard className="p-4 border border-white/[0.08]">
            <SectionTitle
              title="Most Connected Accounts"
              sub="Accounts with the most connections"
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
                    {n.is_bot && <span className="font-mono text-[13px] font-bold text-threat-critical">BOT</span>}
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

    </div>
  );
}
