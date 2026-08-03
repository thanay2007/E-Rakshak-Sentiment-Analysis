import { Bot, ExternalLink, Radar, Share2, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { BotChip, PlatformIcon, ThreatBadge } from "../components/Badges";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import NetworkGraph from "../components/NetworkGraph";
import { SkeletonChart, SkeletonRow } from "../components/Skeletons";
import { threatColor } from "../data/constants";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import type { NetNode } from "../services/api";

const WINDOWS = [
  { label: "24h", hours: 24 },
  { label: "48h", hours: 48 },
  { label: "7d", hours: 168 },
];

function profileUrl(n: NetNode): string | null {
  if (n.platform === "X") return `https://x.com/${n.id}`;
  if (n.platform === "Reddit") return `https://reddit.com/user/${n.id}`;
  if (n.platform === "Facebook") return `https://facebook.com/${n.id}`;
  if (n.platform === "Instagram") return `https://instagram.com/${n.id}`;
  if (n.platform === "Telegram") return `https://t.me/${n.id}`;
  // YouTube nodes are keyed by channel/commenter display name, not by the
  // @handle a channel URL needs — a search lands the analyst on the right
  // channel instead of a fabricated /@name that 404s.
  if (n.platform === "YouTube")
    return `https://www.youtube.com/results?search_query=${encodeURIComponent(n.id)}`;
  return null;
}

const PLATFORMS = ["All", "X", "Reddit", "Facebook", "Instagram", "Telegram", "YouTube"];

export default function NetworkPage() {
  const [hours, setHours] = useState(24);
  const [platform, setPlatform] = useState("All");
  const [selected, setSelected] = useState<NetNode | null>(null);
  const { data, loading } = usePolling(
    () => api.network(hours, platform === "All" ? "" : platform),
    60000,
    [hours, platform]
  );
  const revealRef = useGsapReveal<HTMLDivElement>(data?.clusters.length ?? 0);
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
    ["accounts monitored", data?.nodes.length ?? "—", "in interaction graph"],
    ["interaction links", data?.links.length ?? "—", "coordination + hashtag affinity"],
    ["flagged clusters", data?.clusters.length ?? "—", "near-identical text bursts"],
    ["bot-like accounts", botCount, "handle + timing heuristics"],
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-bold text-slate-200">
            <Share2 size={18} className="text-accent" /> Network Analysis
            <span className="rounded-md border border-accent/30 bg-accent/10 px-1.5 py-0.5 font-mono text-[9px] font-bold tracking-widest text-accent">
              LINK ANALYSIS
            </span>
          </h1>
          <p className="text-xs text-slate-500">
            account interaction graph · influence centrality · coordinated amplification detection
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

      {/* per-platform tabs — police can inspect each app's network in isolation */}
      <div className="flex flex-wrap gap-1.5">
        {PLATFORMS.map((p) => {
          const n = p === "All"
            ? Object.values(counts).reduce((a, b) => a + b, 0)
            : counts[p] ?? 0;
          const active = platform === p;
          return (
            <button
              key={p}
              onClick={() => { setPlatform(p); setSelected(null); }}
              className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-medium transition-all ${
                active
                  ? "border-accent/50 bg-accent/10 text-accent"
                  : "border-white/10 text-slate-400 hover:text-slate-200"
              }`}
            >
              {p !== "All" && <PlatformIcon platform={p} size={16} />}
              {p}
              <span className={`rounded-md px-1.5 py-0.5 font-mono text-[10px] ${active ? "bg-accent/20" : "bg-white/[0.06] text-slate-500"}`}>
                {n}
              </span>
            </button>
          );
        })}
      </div>

      {/* case-board stats */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map(([label, value, sub]) => (
          <GlassCard key={label} className="p-3">
            <div className="text-[9.5px] uppercase tracking-widest text-slate-500">{label}</div>
            <div className="mt-0.5 font-mono text-2xl font-bold text-slate-200">{value}</div>
            <div className="text-[10px] text-slate-600">{sub}</div>
          </GlassCard>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <GlassCard className="p-2 xl:col-span-2">
          {loading && !data ? (
            <SkeletonChart h={620} />
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
          {/* entity profile */}
          {selected ? (
            <GlassCard className="border-accent/30 p-4">
              <SectionTitle title="Entity Profile" right={<Users size={14} className="text-accent" />} />
              <div className="flex items-center gap-2.5">
                <PlatformIcon platform={selected.platform} size={30} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-semibold text-slate-200">{selected.label}</span>
                    {selected.is_bot && <BotChip />}
                  </div>
                  <div className="font-mono text-[11px] text-slate-500">
                    @{selected.id} · {selected.followers.toLocaleString()} followers
                  </div>
                </div>
                {profileUrl(selected) && (
                  <a
                    href={profileUrl(selected)!}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-lg border border-white/10 p-1.5 text-slate-400 hover:bg-white/[0.06]"
                    title="Open profile"
                  >
                    <ExternalLink size={13} />
                  </a>
                )}
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                {[
                  ["avg threat", Math.round(selected.threat)],
                  ["posts", selected.posts],
                  ["influence", (selected.influence * 100).toFixed(1)],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-xl bg-white/[0.04] p-2">
                    <div
                      className="font-mono text-base font-bold"
                      style={{ color: k === "avg threat" ? threatColor(selected.threat) : "#E2E8F0" }}
                    >
                      {v}
                    </div>
                    <div className="text-[9px] uppercase tracking-widest text-slate-500">{k}</div>
                  </div>
                ))}
              </div>
              {selected.cluster && (
                <div className="mt-2 rounded-lg border border-threat-critical/30 bg-threat-critical/10 p-2 font-mono text-[11px] text-threat-critical">
                  ⚠ member of coordinated cluster {selected.cluster}
                </div>
              )}
              {connections.length > 0 && (
                <div className="mt-3">
                  <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Linked accounts ({connections.length})
                  </div>
                  <div className="flex max-h-28 flex-wrap gap-1 overflow-y-auto">
                    {connections.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => setSelected(c)}
                        className="rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-slate-400 hover:bg-white/[0.1] hover:text-slate-200"
                      >
                        @{c.id}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </GlassCard>
          ) : (
            <GlassCard className="p-4">
              <SectionTitle title="Entity Profile" right={<Users size={14} className="text-slate-600" />} />
              <p className="py-4 text-center text-xs text-slate-500">
                Click an account on the board — or a row below — to open its profile.
              </p>
            </GlassCard>
          )}

          {/* influence roster */}
          <GlassCard className="p-4">
            <SectionTitle
              title="Top Influencers"
              sub="degree centrality in window"
              right={<Radar size={14} className="text-slate-600" />}
            />
            {loading && !data ? (
              <SkeletonRow n={5} />
            ) : (
              <div className="space-y-1">
                {topInfluencers.map((n, i) => (
                  <button
                    key={n.id}
                    onClick={() => setSelected(n)}
                    className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-white/[0.05] ${
                      selected?.id === n.id ? "bg-accent/10" : ""
                    }`}
                  >
                    <span className="w-4 font-mono text-[10px] text-slate-600">{i + 1}</span>
                    <PlatformIcon platform={n.platform} size={18} />
                    <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-slate-300">@{n.id}</span>
                    {n.is_bot && <span className="font-mono text-[9px] text-threat-critical">BOT?</span>}
                    <span className="font-mono text-[10px]" style={{ color: threatColor(n.threat) }}>
                      {Math.round(n.threat)}
                    </span>
                    <div className="h-1 w-14 overflow-hidden rounded-full bg-white/[0.07]">
                      <div
                        className="h-full rounded-full bg-accent"
                        style={{
                          width: `${Math.min(100, (n.influence / Math.max(topInfluencers[0]?.influence || 1, 0.001)) * 100)}%`,
                        }}
                      />
                    </div>
                  </button>
                ))}
              </div>
            )}
          </GlassCard>
        </div>
      </div>

      {/* coordinated clusters — full width case cards */}
      <GlassCard className="p-4">
        <SectionTitle
          title="Coordinated Amplification"
          sub={data ? `${data.clusters.length} cluster(s) flagged in window` : undefined}
          right={<Bot size={15} className="text-threat-critical" />}
        />
        {loading && !data ? (
          <SkeletonRow n={2} />
        ) : (
          <div ref={revealRef} className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {data?.clusters.map((c) => (
              <div
                key={c.id}
                className="reveal-item rounded-xl border border-threat-critical/25 bg-threat-critical/[0.04] p-3"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-bold text-threat-critical">{c.id}</span>
                  <ThreatBadge label={c.label} />
                  <span className="font-mono text-[10px] text-slate-500">
                    {c.accounts.length} accounts · {c.posts} posts · avg threat {c.avg_threat}
                  </span>
                  <span className="ml-auto font-mono text-[11px] text-slate-400">
                    conf {(c.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.06]">
                  <div
                    className="h-full rounded-full bg-threat-critical"
                    style={{ width: `${c.confidence * 100}%` }}
                  />
                </div>
                <ul className="mt-2 space-y-1 text-[11px] text-slate-400">
                  {c.why.map((w, i) => (
                    <li key={i} className="flex gap-1.5">
                      <span className="text-threat-critical">▸</span> {w}
                    </li>
                  ))}
                </ul>
                <p className="mt-2 line-clamp-2 rounded-lg bg-black/20 p-2 text-[11px] italic text-slate-500">
                  “{c.sample_text}”
                </p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {c.accounts.slice(0, 8).map((a) => (
                    <span key={a} className="rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                      @{a}
                    </span>
                  ))}
                  {c.accounts.length > 8 && (
                    <span className="font-mono text-[10px] text-slate-600">+{c.accounts.length - 8} more</span>
                  )}
                </div>
              </div>
            ))}
            {data?.clusters.length === 0 && (
              <p className="col-span-full py-6 text-center text-xs text-slate-500">
                No coordinated behavior detected in this window — the board shows organic activity only.
              </p>
            )}
          </div>
        )}
      </GlassCard>
    </div>
  );
}
