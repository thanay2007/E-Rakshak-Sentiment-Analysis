import {
  Activity, ArrowUpRight, Download, Eye, Hash, Layers, MapPin, PackagePlus,
  Plus, Search, Sparkles, Trash2, Type, Upload, UserRound, X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import { SkeletonRow } from "../components/Skeletons";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { api, WatchItem } from "../services/api";

const KIND_META: Record<string, { icon: typeof Type; color: string; label: string }> = {
  keyword: { icon: Type, color: "#14B8C4", label: "Keywords" },
  hashtag: { icon: Hash, color: "#A855F7", label: "Hashtags" },
  account: { icon: UserRound, color: "#F59E0B", label: "Target Accounts" },
  location: { icon: MapPin, color: "#10B981", label: "Locations & Districts" },
};

const PRIORITY_META: Record<string, { color: string; rank: number }> = {
  critical: { color: "#EF4444", rank: 0 },
  high: { color: "#F59E0B", rank: 1 },
  medium: { color: "#14B8C4", rank: 2 },
  low: { color: "#64748B", rank: 3 },
};

function PriorityBadge({ p }: { p: string }) {
  const meta = PRIORITY_META[p] ?? PRIORITY_META.medium;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border px-2 py-0.2 font-mono text-[9.5px] font-bold uppercase tracking-wider"
      style={{ color: meta.color, borderColor: `${meta.color}55`, backgroundColor: `${meta.color}14` }}
    >
      {p}
    </span>
  );
}

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/** Where a rule's matches live in the feed, so a rule can be inspected rather
 *  than only counted. A location rule filters by district; everything else is
 *  a text search, which is what the crawler matched on in the first place. */
function feedHrefFor(w: WatchItem): string {
  if (w.kind === "location") return `/app/feed?location=${encodeURIComponent(w.value)}`;
  return `/app/feed?q=${encodeURIComponent(w.value.replace(/^[@#]/, ""))}`;
}

export default function Watchlist() {
  const { data, loading, refresh } = usePolling(() => api.watchlist(), 30000);
  const { data: presets } = usePolling(() => api.watchPresets(), 300000);
  const { data: suggestions, refresh: refreshSuggestions } =
    usePolling(() => api.watchSuggestions(24), 120000);
  const [kind, setKind] = useState("keyword");
  const [priority, setPriority] = useState("medium");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | "active" | "paused">("all");
  const [showBulk, setShowBulk] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<string[]>([]);
  const [purgeArmed, setPurgeArmed] = useState(false);
  const revealRef = useGsapReveal<HTMLDivElement>(data?.length ?? 0);

  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4000);
  };

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    await api.addWatch({ kind, value: value.trim(), note: note.trim(), priority });
    setValue("");
    setNote("");
    refresh();
  };

  const applyPreset = async (slug: string) => {
    setBusy(slug);
    try {
      const r = await api.applyWatchPreset(slug);
      flash(`${r.pack}: ${r.added} added, ${r.skipped} already tracked`);
      refresh();
    } finally {
      setBusy(null);
    }
  };

  const importBulk = async () => {
    const items = bulkText
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((line) => {
        const [v, n] = line.split("|").map((s) => s.trim());
        const isTag = v.startsWith("#");
        return { kind: isTag ? "hashtag" : kind, value: isTag ? v.slice(1) : v, note: n ?? "", priority };
      });
    if (!items.length) return;
    setBusy("bulk");
    try {
      const r = await api.bulkAddWatch(items);
      flash(`Bulk import: ${r.added} added, ${r.skipped} skipped`);
      setBulkText("");
      setShowBulk(false);
      refresh();
    } finally {
      setBusy(null);
    }
  };

  const acceptSuggestion = async (s: { kind: string; value: string; reason: string }) => {
    setBusy(`sug-${s.value}`);
    try {
      await api.addWatch({
        kind: s.kind, value: s.value, priority: "high",
        note: `Accepted from spike suggestion — ${s.reason}`,
      });
      flash(`Now watching “${s.value}”`);
      refresh();
      refreshSuggestions();
    } finally {
      setBusy(null);
    }
  };

  const removeInactive = async () => {
    const dead = (data ?? []).filter((w) => !w.active);
    setBusy("purge");
    try {
      await Promise.all(dead.map((w) => api.deleteWatch(w.id)));
      flash(`Removed ${dead.length} paused rule${dead.length === 1 ? "" : "s"}`);
      refresh();
      refreshSuggestions();
    } finally {
      setBusy(null);
      setPurgeArmed(false);
    }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = data ?? [];
    if (status !== "all") rows = rows.filter((w) => (status === "active" ? w.active : !w.active));
    if (!q) return rows;
    return rows.filter(
      (w) =>
        w.value.toLowerCase().includes(q) ||
        w.note.toLowerCase().includes(q) ||
        (w.category ?? "").toLowerCase().includes(q) ||
        w.priority.includes(q)
    );
  }, [data, query, status]);

  const openSuggestions = (suggestions ?? []).filter((s) => !dismissed.includes(s.value));
  const inactiveCount = (data ?? []).filter((w) => !w.active).length;
  const silentCount = (data ?? []).filter((w) => w.active && (w.hits_7d ?? 0) === 0).length;

  const stats = useMemo(() => {
    const all = data ?? [];
    return {
      total: all.length,
      active: all.filter((w) => w.active).length,
      hits: all.reduce((s, w) => s + (w.hits_7d ?? 0), 0),
      critical: all.filter((w) => w.priority === "critical").length,
    };
  }, [data]);

  const sortItems = (items: WatchItem[]) =>
    [...items].sort(
      (a, b) =>
        (PRIORITY_META[a.priority]?.rank ?? 2) - (PRIORITY_META[b.priority]?.rank ?? 2) ||
        (b.hits_7d ?? 0) - (a.hits_7d ?? 0)
    );

  return (
    <div className="space-y-4">
      {/* Executive Command Bar */}
      <div className="flex flex-col gap-3 rounded-2xl border border-white/[0.08] bg-base-950/80 p-4 shadow-xl backdrop-blur-xl md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-accent/40 bg-accent/15 text-accent shadow-[0_0_15px_rgba(20,184,196,0.25)]">
            <Eye size={20} />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-white sm:text-base">
              Autonomous Watchlist & Radar Rules
            </h1>
            <p className="text-xs text-slate-400">
              Steer crawler algorithms · Priority-ranked keywords, hashtags, handles & districts
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => void api.downloadWatchlist()}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-bold text-slate-200 hover:bg-white/[0.08] hover:text-accent transition-all shadow-sm"
          >
            <Download size={13} /> Export CSV
          </button>
          <button
            onClick={() => setShowBulk((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-bold text-slate-200 hover:bg-white/[0.08] hover:text-accent transition-all shadow-sm"
          >
            <Upload size={13} /> Bulk Import
          </button>
        </div>
      </div>

      {/* Summary Stat Tiles */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Terms Tracked", stats.total, "#14B8C4"],
          ["Active Rules", stats.active, "#10B981"],
          ["Hits (Last 7 Days)", stats.hits, "#A855F7"],
          ["Critical Priority", stats.critical, "#EF4444"],
        ].map(([label, n, color]) => (
          <GlassCard key={label as string} className="p-3.5 border border-white/[0.08]">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</div>
            <div className="mt-1 font-mono text-2xl font-black" style={{ color: color as string }}>
              {n as number}
            </div>
          </GlassCard>
        ))}
      </div>

      {/* Suggested targets.
          These used to be inserted straight into the watchlist by the trends
          page on every poll — rules nobody chose, appearing from a GET. They
          are now offered here and only become rules when accepted. */}
      {openSuggestions.length > 0 && (
        <GlassCard className="border border-accent/25 bg-accent/[0.03] p-4">
          <SectionTitle
            title="Suggested Targets"
            sub="Terms spiking negative in the last 24h that you are not watching yet"
            right={<Sparkles size={16} className="text-accent" />}
          />
          <div className="space-y-2">
            {openSuggestions.map((s) => (
              <div key={`${s.kind}-${s.value}`}
                className="flex flex-wrap items-center gap-2.5 rounded-xl border border-white/[0.07] bg-base-950/60 px-3 py-2">
                <span className="font-mono text-xs font-bold text-slate-100">
                  {s.kind === "hashtag" ? "#" : ""}{s.value}
                </span>
                <span className="rounded-md border border-white/10 px-1.5 py-0.5 text-[9.5px] uppercase tracking-wider text-slate-400">
                  {s.kind}
                </span>
                <span className="text-[11px] text-slate-400">{s.reason}</span>
                <div className="ml-auto flex items-center gap-1.5">
                  <Link to={`/app/feed?q=${encodeURIComponent(s.value)}`}
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1 text-[11px] font-semibold text-slate-300 hover:text-accent">
                    inspect <ArrowUpRight size={11} />
                  </Link>
                  <button onClick={() => void acceptSuggestion(s)} disabled={busy === `sug-${s.value}`}
                    className="rounded-lg bg-accent px-2.5 py-1 text-[11px] font-black text-base-950 hover:bg-accent-light disabled:opacity-50">
                    {busy === `sug-${s.value}` ? "Adding…" : "Watch"}
                  </button>
                  <button onClick={() => setDismissed((d) => [...d, s.value])}
                    aria-label="Dismiss suggestion"
                    className="rounded-lg p-1 text-slate-500 hover:text-slate-200">
                    <X size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      {/* Rule health — a watchlist nobody prunes stops being a watchlist. */}
      {(inactiveCount > 0 || silentCount > 0) && (
        <GlassCard className="flex flex-wrap items-center gap-3 border border-white/[0.08] p-3.5 text-[11.5px]">
          {silentCount > 0 && (
            <span className="text-slate-400">
              <strong className="text-slate-200">{silentCount}</strong> active rule{silentCount === 1 ? "" : "s"} matched
              nothing in 7 days
            </span>
          )}
          {inactiveCount > 0 && (
            <>
              <span className="text-slate-400">
                <strong className="text-slate-200">{inactiveCount}</strong> paused rule{inactiveCount === 1 ? "" : "s"} are
                steering nothing
              </span>
              <button
                onClick={() => (purgeArmed ? void removeInactive() : setPurgeArmed(true))}
                disabled={busy === "purge"}
                className={`ml-auto inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 font-bold disabled:opacity-50 ${
                  purgeArmed
                    ? "border-threat-critical bg-threat-critical/20 text-threat-critical"
                    : "border-white/[0.1] bg-white/[0.04] text-slate-400 hover:border-threat-critical/40 hover:text-threat-critical"
                }`}
              >
                <Trash2 size={12} />
                {busy === "purge" ? "Removing…" : purgeArmed ? "Click again to delete them" : "Remove paused rules"}
              </button>
            </>
          )}
        </GlassCard>
      )}

      {/* Preset Packs */}
      <GlassCard className="p-4 border border-white/[0.08]">
        <SectionTitle
          title="Rapid-Deploy Threat Intelligence Packs"
          sub="Curated term sets for emerging riots, scams, election rumors, and disaster misinformation"
          right={<PackagePlus size={16} className="text-accent" />}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          {(presets ?? []).map((p) => (
            <button
              key={p.slug}
              onClick={() => applyPreset(p.slug)}
              disabled={busy === p.slug}
              title={p.description}
              className="inline-flex items-center gap-1.5 rounded-xl border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs font-bold text-accent transition-all hover:bg-accent/25 disabled:opacity-50 shadow-sm"
            >
              <Layers size={13} />
              {busy === p.slug ? "Deploying…" : p.title}
              <span className="rounded-md bg-accent/20 px-1.5 py-0.2 font-mono text-[10px] font-extrabold">{p.count}</span>
            </button>
          ))}
        </div>
        {toast && <p className="mt-2.5 text-xs font-semibold text-threat-neutral">{toast}</p>}
      </GlassCard>

      {/* Add Form & Search */}
      <GlassCard className="p-4 border border-white/[0.08]">
        <form onSubmit={add} className="flex flex-wrap items-center gap-2.5">
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="rounded-xl border border-white/[0.1] bg-base-800 py-2 pl-3 pr-8 text-xs text-slate-200 hover:border-white/20 focus:border-accent/60 focus:outline-none"
          >
            {Object.keys(KIND_META).map((k) => (
              <option key={k} value={k}>{KIND_META[k].label}</option>
            ))}
          </select>
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className="rounded-xl border border-white/[0.1] bg-base-800 py-2 pl-3 pr-8 text-xs text-slate-200 hover:border-white/20 focus:border-accent/60 focus:outline-none"
          >
            {Object.keys(PRIORITY_META).map((p) => (
              <option key={p} value={p}>{p.toUpperCase()} Priority</option>
            ))}
          </select>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Term to monitor (Hindi, Gujarati, Hinglish, handle...)"
            className="min-w-[240px] flex-1 rounded-xl border border-white/[0.1] bg-white/[0.04] px-3.5 py-2 text-xs text-slate-100 placeholder:text-slate-500 focus:border-accent/60 focus:bg-white/[0.07] focus:outline-none"
          />
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Analyst context / case ID (optional)"
            className="w-56 rounded-xl border border-white/[0.1] bg-white/[0.04] px-3.5 py-2 text-xs text-slate-100 placeholder:text-slate-500 focus:border-accent/60 focus:bg-white/[0.07] focus:outline-none"
          />
          <button
            type="submit"
            className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-4 py-2 text-xs font-black text-base-950 shadow-md shadow-accent/20 hover:bg-accent-light transition-all"
          >
            <Plus size={14} /> Add Rule
          </button>
          <div className="ml-auto flex items-center gap-2">
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as "all" | "active" | "paused")}
              className="rounded-xl border border-white/[0.1] bg-base-800 py-2 pl-3 pr-8 text-xs text-slate-200 hover:border-white/20 focus:border-accent/60 focus:outline-none"
            >
              <option value="all">All rules</option>
              <option value="active">Active only</option>
              <option value="paused">Paused only</option>
            </select>
            <div className="relative">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter watchlist…"
                className="w-48 rounded-xl border border-white/[0.1] bg-white/[0.04] py-2 pl-9 pr-3 text-xs text-slate-100 placeholder:text-slate-500 focus:border-accent/60 focus:outline-none"
              />
            </div>
          </div>
        </form>

        {showBulk && (
          <div className="mt-3.5 rounded-xl border border-white/[0.08] bg-base-950/80 p-3.5 backdrop-blur-md">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-slate-300">
                Enter one term per line (<code className="font-mono text-accent">term | optional note</code>). Lines starting with <code className="font-mono text-accent">#</code> automatically become hashtags.
              </span>
              <button onClick={() => setShowBulk(false)} className="text-slate-400 hover:text-slate-200">
                <X size={15} />
              </button>
            </div>
            <textarea
              value={bulkText}
              onChange={(e) => setBulkText(e.target.value)}
              rows={5}
              placeholder={"बच्चा चोर | rumor trigger\n#FinalWarning\nrasta roko | road-block call\n@suspicious_handle | bot network seed"}
              className="w-full rounded-xl border border-white/[0.1] bg-white/[0.03] p-3 font-mono text-xs text-slate-100 placeholder:text-slate-600 focus:border-accent/60 focus:outline-none"
            />
            <button
              onClick={importBulk}
              disabled={busy === "bulk" || !bulkText.trim()}
              className="mt-2.5 inline-flex items-center gap-1.5 rounded-xl bg-accent px-4 py-2 text-xs font-black text-base-950 shadow-md shadow-accent/20 hover:bg-accent-light disabled:opacity-50 transition-all"
            >
              <Upload size={13} /> {busy === "bulk" ? "Importing…" : "Import All Rules"}
            </button>
          </div>
        )}
      </GlassCard>

      {/* Grid of Rule Groups */}
      {loading && !data ? (
        <SkeletonRow n={4} />
      ) : (
        <div ref={revealRef} className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {Object.entries(KIND_META).map(([k, meta]) => {
            const items = sortItems(filtered.filter((w) => w.kind === k));
            const Icon = meta.icon;
            return (
              <GlassCard key={k} className="reveal-item p-4 border border-white/[0.08]">
                <SectionTitle
                  title={meta.label}
                  sub={`${items.length} rules active · ${items.reduce((s, w) => s + (w.hits_7d ?? 0), 0)} hits in 7d window`}
                  right={<Icon size={16} style={{ color: meta.color }} />}
                />
                <div className="mt-3 max-h-96 space-y-2 overflow-y-auto pr-1">
                  {items.map((w) => (
                    <div
                      key={w.id}
                      className="rounded-xl border border-white/[0.06] bg-base-950/60 p-3 backdrop-blur-md transition-all hover:border-white/15 hover:bg-base-950/80"
                    >
                      <div className="flex items-center gap-2.5">
                        <button
                          onClick={async () => {
                            await api.updateWatch(w.id, { active: !w.active });
                            refresh();
                          }}
                          className={`h-4 w-7 shrink-0 rounded-full p-0.5 transition-colors ${w.active ? "bg-accent" : "bg-white/15"}`}
                          aria-label={w.active ? "Deactivate" : "Activate"}
                        >
                          <span
                            className={`block h-3 w-3 rounded-full bg-base-950 transition-transform ${w.active ? "translate-x-3" : ""}`}
                          />
                        </button>
                        <span
                          className={`truncate text-xs font-bold ${w.active ? "text-slate-100" : "text-slate-500 line-through"}`}
                        >
                          {w.value}
                        </span>
                        <PriorityBadge p={w.priority} />
                        <div className="ml-auto flex items-center gap-1">
                          <Link
                            to={feedHrefFor(w)}
                            title="Open the posts this rule matched"
                            className="rounded-lg p-1 text-slate-500 transition-all hover:bg-accent/15 hover:text-accent"
                          >
                            <ArrowUpRight size={13} />
                          </Link>
                          <button
                            onClick={async () => {
                              await api.deleteWatch(w.id);
                              refresh();
                            }}
                            className="rounded-lg p-1 text-slate-500 hover:bg-threat-critical/20 hover:text-threat-critical transition-all"
                            aria-label="Delete rule"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>

                      <div className="mt-2 flex flex-wrap items-center gap-3 pl-9 text-[11px] text-slate-400">
                        <span className={`inline-flex items-center gap-1 font-mono font-bold ${(w.hits_7d ?? 0) > 0 ? "text-accent" : ""}`}>
                          <Activity size={11} /> {w.hits_7d ?? 0} hits
                        </span>
                        <span>Last: {timeAgo(w.last_hit)}</span>
                        {(w.top_threat ?? 0) >= 50 && (
                          <span className="font-mono font-bold text-threat-critical">
                            Peak {Math.round(w.top_threat)}
                          </span>
                        )}
                        {w.note && <span className="truncate italic text-slate-400">— {w.note}</span>}
                      </div>
                    </div>
                  ))}
                  {items.length === 0 && (
                    <p className="py-6 text-center text-xs text-slate-400">
                      {query ? "No rules match search query." : "No terms tracked in this category."}
                    </p>
                  )}
                </div>
              </GlassCard>
            );
          })}
        </div>
      )}
    </div>
  );
}
