import {
  Activity, Download, Eye, Hash, Lightbulb, MapPin, Plus, Search,
  Trash2, Type, Upload, UserRound, X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import { SkeletonRow } from "../components/Skeletons";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { api, WatchItem, WatchSuggestion } from "../services/api";

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
      className="inline-flex items-center gap-1 rounded-md border px-2 py-0.2 font-mono text-[13px] font-bold uppercase tracking-wider"
      style={{ color: meta.color, borderColor: `${meta.color}55`, backgroundColor: `${meta.color}14` }}
    >
      {p}
    </span>
  );
}

const STATUS_META: Record<WatchItem["status"], { color: string; label: string; hint: string }> = {
  rising: { color: "#EF4444", label: "Rising", hint: "Firing more often than usual in the last 24 hours" },
  active: { color: "#14B8C4", label: "Active", hint: "Firing at its usual rate" },
  cooling: { color: "#94A3B8", label: "Cooling", hint: "Firing less than usual in the last 24 hours" },
  dormant: { color: "#64748B", label: "Dormant", hint: "No matches in the last 3 days — consider pausing or removing" },
};

function StatusChip({ status }: { status: WatchItem["status"] }) {
  const meta = STATUS_META[status] ?? STATUS_META.dormant;
  return (
    <span
      title={meta.hint}
      className="inline-flex items-center rounded-md border px-1.5 text-[11px] font-bold uppercase tracking-wider"
      style={{ color: meta.color, borderColor: `${meta.color}44` }}
    >
      {meta.label}
    </span>
  );
}

/** Current relevance (0-100). Recomputed from live hits on every poll, so it
 *  falls on its own once a term stops matching new posts. */
function RelevanceBar({ value }: { value: number }) {
  const color = value >= 70 ? "#EF4444" : value >= 40 ? "#F59E0B" : value > 0 ? "#14B8C4" : "#475569";
  return (
    <span className="inline-flex items-center gap-1.5" title="Relevance now: recent hits, recent severity and how recently it matched">
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-white/10">
        <span className="block h-full rounded-full" style={{ width: `${Math.max(2, value)}%`, backgroundColor: color }} />
      </span>
      <span className="font-mono font-bold" style={{ color }}>{value}</span>
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

export default function Watchlist() {
  const { data, loading, refresh } = usePolling(() => api.watchlist(), 30000);
  const { data: suggestions, refresh: refreshSuggestions } = usePolling(() => api.watchSuggestions(24), 120000);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [kind, setKind] = useState("keyword");
  const [priority, setPriority] = useState("medium");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [query, setQuery] = useState("");
  const [showBulk, setShowBulk] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  // On/off flips shown immediately, before the server confirms. Each entry is
  // dropped once polled data agrees with it, or reverted if the save fails —
  // the switch used to wait for the save AND a reload of the whole list.
  const [activeOverride, setActiveOverride] = useState<Record<string, boolean>>({});
  const items = useMemo(
    () => (data ?? []).map((w) => (w.id in activeOverride ? { ...w, active: activeOverride[w.id] } : w)),
    [data, activeOverride]
  );
  useEffect(() => {
    if (!data) return;
    setActiveOverride((cur) => {
      const next = { ...cur };
      for (const w of data) if (w.id in next && next[w.id] === w.active) delete next[w.id];
      return Object.keys(next).length === Object.keys(cur).length ? cur : next;
    });
  }, [data]);
  const revealRef = useGsapReveal<HTMLDivElement>(data?.length ?? 0);

  const toggleActive = (w: WatchItem) => {
    const next = !w.active;
    setActiveOverride((cur) => ({ ...cur, [w.id]: next }));
    api.updateWatch(w.id, { active: next })
      .then(() => refresh())
      .catch((e: unknown) => {
        setActiveOverride((cur) => {
          const rest = { ...cur };
          delete rest[w.id];
          return rest;
        });
        flash(`Could not ${next ? "turn on" : "turn off"} "${w.value}": ${e instanceof Error ? e.message : "save failed"}`);
      });
  };

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


  const acceptSuggestion = async (sg: WatchSuggestion) => {
    const key = `${sg.kind}:${sg.value}`;
    setBusy(key);
    try {
      await api.addWatch({ kind: sg.kind, value: sg.value, note: `Suggested: ${sg.reason}`, priority: sg.priority ?? "medium" });
      flash(`Now watching ${sg.kind} "${sg.value}"`);
      refresh();
      refreshSuggestions();
    } finally {
      setBusy(null);
    }
  };

  const visibleSuggestions = (suggestions ?? []).filter((sg) => !dismissed.has(`${sg.kind}:${sg.value}`));

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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (w) =>
        w.value.toLowerCase().includes(q) ||
        w.note.toLowerCase().includes(q) ||
        (w.category ?? "").toLowerCase().includes(q) ||
        w.priority.includes(q)
    );
  }, [items, query]);

  const stats = useMemo(() => {
    const all = items;
    return {
      total: all.length,
      active: all.filter((w) => w.active).length,
      hits: all.reduce((s, w) => s + (w.hits_7d ?? 0), 0),
      dormant: all.filter((w) => w.status === "dormant").length,
    };
  }, [items]);

  const sortItems = (items: WatchItem[]) =>
    [...items].sort(
      (a, b) =>
        Number(a.status === "dormant") - Number(b.status === "dormant") ||
        (b.relevance ?? 0) - (a.relevance ?? 0) ||
        (PRIORITY_META[a.priority]?.rank ?? 2) - (PRIORITY_META[b.priority]?.rank ?? 2)
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
          ["Dormant (3d+)", stats.dormant, "#64748B"],
        ].map(([label, n, color]) => (
          <GlassCard key={label as string} className="p-3.5 border border-white/[0.08]">
            <div className="text-xs font-bold uppercase tracking-wider text-slate-400">{label}</div>
            <div className="mt-1 font-mono text-2xl font-black" style={{ color: color as string }}>
              {n as number}
            </div>
          </GlassCard>
        ))}
      </div>

      {/* Suggestions — recomputed from the last 24h on every poll, never auto-added */}
      <GlassCard className="p-4 border border-white/[0.08]">
        <SectionTitle
          title="Suggested Additions"
          sub="Terms, accounts and locations showing concerning activity in the last 24 hours that are not on the watchlist yet"
          right={<Lightbulb size={16} className="text-accent" />}
        />
        {visibleSuggestions.length ? (
          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {visibleSuggestions.map((sg) => {
              const meta = KIND_META[sg.kind] ?? KIND_META.keyword;
              const Icon = meta.icon;
              const key = `${sg.kind}:${sg.value}`;
              return (
                <div key={key} className="flex items-start gap-2.5 rounded-xl border border-white/[0.06] bg-base-950/60 p-3">
                  <Icon size={14} className="mt-0.5 shrink-0" style={{ color: meta.color }} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-xs font-bold text-slate-100">
                        {sg.kind === "hashtag" ? "#" : sg.kind === "account" ? "@" : ""}{sg.value}
                      </span>
                      <PriorityBadge p={sg.priority ?? "medium"} />
                    </div>
                    <p className="mt-1 text-[12px] leading-snug text-slate-400">{sg.reason}</p>
                  </div>
                  <div className="flex shrink-0 flex-col gap-1">
                    <button
                      onClick={() => void acceptSuggestion(sg)}
                      disabled={busy === key}
                      className="inline-flex items-center gap-1 rounded-lg bg-accent px-2 py-1 text-[11px] font-black text-base-950 hover:bg-accent-light disabled:opacity-50"
                    >
                      <Plus size={11} /> {busy === key ? "Adding…" : "Add"}
                    </button>
                    <button
                      onClick={() => setDismissed((d) => new Set(d).add(key))}
                      className="rounded-lg px-2 py-0.5 text-[11px] text-slate-500 hover:text-slate-300"
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="mt-3 text-xs text-slate-400">No new suggestions right now — nothing unwatched is showing concerning activity.</p>
        )}
      </GlassCard>


      {/* Add Form & Search */}
      <GlassCard className="p-4 border border-white/[0.08]">
        {toast && <p className="mb-2.5 text-xs font-semibold text-threat-neutral">{toast}</p>}
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
          <div className="relative ml-auto">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter watchlist…"
              className="w-48 rounded-xl border border-white/[0.1] bg-white/[0.04] py-2 pl-9 pr-3 text-xs text-slate-100 placeholder:text-slate-500 focus:border-accent/60 focus:outline-none"
            />
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
                  sub={`${items.filter((w) => w.active).length} rules active · ${items.reduce((s, w) => s + (w.hits_24h ?? 0), 0)} hits in 24h · ${items.reduce((s, w) => s + (w.hits_7d ?? 0), 0)} in 7d`}
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
                          onClick={() => toggleActive(w)}
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
                        <StatusChip status={w.status} />
                        <button
                          onClick={async () => {
                            await api.deleteWatch(w.id);
                            refresh();
                          }}
                          className="ml-auto rounded-lg p-1 text-slate-500 hover:bg-threat-critical/20 hover:text-threat-critical transition-all"
                          aria-label="Delete rule"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>

                      <div className="mt-2 flex flex-wrap items-center gap-3 pl-9 text-[13px] text-slate-400">
                        <RelevanceBar value={w.relevance ?? 0} />
                        <span className={`inline-flex items-center gap-1 font-mono font-bold ${(w.hits_24h ?? 0) > 0 ? "text-accent" : ""}`}>
                          <Activity size={11} /> {w.hits_24h ?? 0} today · {w.hits_7d ?? 0} in 7d
                        </span>
                        <span>Last: {timeAgo(w.last_hit)}</span>
                        {(w.peak_24h ?? 0) >= 50 && (
                          <span className="font-mono font-bold text-threat-critical" title="Highest concern score among today's matches">
                            Peak today {Math.round(w.peak_24h)}
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
