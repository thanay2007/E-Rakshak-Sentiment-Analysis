import {
  Activity, Download, Eye, Hash, Layers, MapPin, PackagePlus, Plus, Search,
  Trash2, Type, Upload, UserRound, X,
} from "lucide-react";
import { useMemo, useState } from "react";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import { SkeletonRow } from "../components/Skeletons";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { api, WatchItem } from "../services/api";

const KIND_META: Record<string, { icon: typeof Type; color: string; label: string }> = {
  keyword: { icon: Type, color: "#14B8C4", label: "Keywords" },
  hashtag: { icon: Hash, color: "#A855F7", label: "Hashtags" },
  account: { icon: UserRound, color: "#F59E0B", label: "Accounts" },
  location: { icon: MapPin, color: "#10B981", label: "Locations" },
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
      className="inline-flex items-center gap-1 rounded-full border px-1.5 py-px text-[9px] font-bold uppercase tracking-wider"
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

export default function Watchlist() {
  const { data, loading, refresh } = usePolling(() => api.watchlist(), 30000);
  const { data: presets } = usePolling(() => api.watchPresets(), 300000);
  const [kind, setKind] = useState("keyword");
  const [priority, setPriority] = useState("medium");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [query, setQuery] = useState("");
  const [showBulk, setShowBulk] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
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
        // "value | note" or bare value; hashtags may start with #
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
    if (!q) return data ?? [];
    return (data ?? []).filter(
      (w) =>
        w.value.toLowerCase().includes(q) ||
        w.note.toLowerCase().includes(q) ||
        (w.category ?? "").toLowerCase().includes(q) ||
        w.priority.includes(q)
    );
  }, [data, query]);

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
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-bold text-slate-200">
            <Eye size={18} className="text-accent" /> Watchlist
          </h1>
          <p className="text-xs text-slate-500">
            monitored terms steering live crawling — priority-ranked, with real hit statistics from the last 7 days
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void api.downloadWatchlist()}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs font-semibold text-slate-300 hover:border-accent/40 hover:text-accent"
          >
            <Download size={13} /> Export CSV
          </button>
          <button
            onClick={() => setShowBulk((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs font-semibold text-slate-300 hover:border-accent/40 hover:text-accent"
          >
            <Upload size={13} /> Bulk import
          </button>
        </div>
      </div>

      {/* summary strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Terms tracked", stats.total, "#14B8C4"],
          ["Active", stats.active, "#10B981"],
          ["Hits · 7 days", stats.hits, "#A855F7"],
          ["Critical priority", stats.critical, "#EF4444"],
        ].map(([label, n, color]) => (
          <GlassCard key={label as string} className="p-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
            <div className="mt-1 font-mono text-xl font-bold" style={{ color: color as string }}>
              {n as number}
            </div>
          </GlassCard>
        ))}
      </div>

      {/* preset packs */}
      <GlassCard className="p-4">
        <SectionTitle
          title="Monitoring Packs"
          sub="curated term sets — one click to deploy, duplicates skipped"
          right={<PackagePlus size={15} className="text-slate-600" />}
        />
        <div className="flex flex-wrap gap-2">
          {(presets ?? []).map((p) => (
            <button
              key={p.slug}
              onClick={() => applyPreset(p.slug)}
              disabled={busy === p.slug}
              title={p.description}
              className="inline-flex items-center gap-1.5 rounded-xl border border-accent/30 bg-accent/10 px-3 py-1.5 text-xs font-semibold text-accent transition-colors hover:bg-accent hover:text-base-900 disabled:opacity-50"
            >
              <Layers size={12} />
              {busy === p.slug ? "Deploying…" : p.title}
              <span className="rounded-full bg-black/20 px-1.5 font-mono text-[10px]">{p.count}</span>
            </button>
          ))}
        </div>
        {toast && <p className="mt-2 text-[11px] font-medium text-threat-neutral">{toast}</p>}
      </GlassCard>

      {/* add form + search */}
      <GlassCard className="p-4">
        <form onSubmit={add} className="flex flex-wrap items-center gap-2">
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="rounded-xl border border-white/[0.08] bg-base-800 py-2 pl-2.5 pr-8 text-xs text-slate-400"
          >
            {Object.keys(KIND_META).map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className="rounded-xl border border-white/[0.08] bg-base-800 py-2 pl-2.5 pr-8 text-xs text-slate-400"
          >
            {Object.keys(PRIORITY_META).map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Term to monitor (any language / script)"
            className="w-56 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:border-accent/40 focus:outline-none"
          />
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Analyst note (optional)"
            className="w-48 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:border-accent/40 focus:outline-none"
          />
          <button
            type="submit"
            className="glow-accent inline-flex items-center gap-1.5 rounded-xl border border-accent/50 bg-accent/15 px-4 py-2 text-xs font-bold text-accent hover:bg-accent hover:text-base-900"
          >
            <Plus size={13} /> Add
          </button>
          <div className="relative ml-auto">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-600" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter terms…"
              className="w-44 rounded-xl border border-white/[0.08] bg-white/[0.04] py-2 pl-8 pr-3 text-xs text-slate-200 placeholder:text-slate-600 focus:border-accent/40 focus:outline-none"
            />
          </div>
        </form>

        {showBulk && (
          <div className="mt-3 rounded-xl border border-white/[0.08] bg-black/20 p-3">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-[11px] font-semibold text-slate-400">
                One term per line — <code className="font-mono">term | note</code>. Lines starting with # become hashtags;
                everything else uses the kind/priority selected above.
              </span>
              <button onClick={() => setShowBulk(false)} className="text-slate-600 hover:text-slate-300">
                <X size={14} />
              </button>
            </div>
            <textarea
              value={bulkText}
              onChange={(e) => setBulkText(e.target.value)}
              rows={5}
              placeholder={"बच्चा चोर | rumor trigger\n#FinalWarning\nrasta roko | road-block call"}
              className="w-full rounded-lg border border-white/[0.08] bg-white/[0.03] p-2.5 font-mono text-xs text-slate-200 placeholder:text-slate-600 focus:border-accent/40 focus:outline-none"
            />
            <button
              onClick={importBulk}
              disabled={busy === "bulk" || !bulkText.trim()}
              className="mt-2 inline-flex items-center gap-1.5 rounded-xl border border-accent/50 bg-accent/15 px-4 py-2 text-xs font-bold text-accent hover:bg-accent hover:text-base-900 disabled:opacity-50"
            >
              <Upload size={13} /> {busy === "bulk" ? "Importing…" : "Import all"}
            </button>
          </div>
        )}
      </GlassCard>

      {loading && !data ? (
        <SkeletonRow n={4} />
      ) : (
        <div ref={revealRef} className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {Object.entries(KIND_META).map(([k, meta]) => {
            const items = sortItems(filtered.filter((w) => w.kind === k));
            const Icon = meta.icon;
            return (
              <GlassCard key={k} className="reveal-item p-4">
                <SectionTitle
                  title={meta.label}
                  sub={`${items.length} tracked · ${items.reduce((s, w) => s + (w.hits_7d ?? 0), 0)} hits/7d`}
                  right={<Icon size={15} style={{ color: meta.color }} />}
                />
                <div className="max-h-96 space-y-2 overflow-y-auto pr-1">
                  {items.map((w) => (
                    <div
                      key={w.id}
                      className="rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2"
                    >
                      <div className="flex items-center gap-2.5">
                        <button
                          onClick={async () => {
                            await api.updateWatch(w.id, { active: !w.active });
                            refresh();
                          }}
                          className={`h-4 w-7 shrink-0 rounded-full p-0.5 transition-colors ${w.active ? "bg-accent/70" : "bg-white/10"}`}
                          aria-label={w.active ? "Deactivate" : "Activate"}
                        >
                          <span
                            className={`block h-3 w-3 rounded-full bg-white transition-transform ${w.active ? "translate-x-3" : ""}`}
                          />
                        </button>
                        <span
                          className={`truncate text-[12.5px] font-medium ${w.active ? "text-slate-200" : "text-slate-600 line-through"}`}
                        >
                          {w.value}
                        </span>
                        <PriorityBadge p={w.priority} />
                        <button
                          onClick={async () => {
                            await api.deleteWatch(w.id);
                            refresh();
                          }}
                          className="ml-auto rounded-lg p-1 text-slate-600 hover:bg-threat-critical/15 hover:text-threat-critical"
                          aria-label="Delete"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                      <div className="mt-1 flex items-center gap-3 pl-9 text-[10.5px] text-slate-600">
                        <span className={`inline-flex items-center gap-1 font-mono ${(w.hits_7d ?? 0) > 0 ? "text-accent" : ""}`}>
                          <Activity size={10} /> {w.hits_7d ?? 0} hits
                        </span>
                        <span>last: {timeAgo(w.last_hit)}</span>
                        {(w.top_threat ?? 0) >= 50 && (
                          <span className="font-mono font-bold text-threat-critical">peak {Math.round(w.top_threat)}</span>
                        )}
                        {w.category && <span className="truncate text-slate-700">{w.category}</span>}
                        {w.note && <span className="truncate">— {w.note}</span>}
                      </div>
                    </div>
                  ))}
                  {items.length === 0 && (
                    <p className="py-3 text-center text-[11px] text-slate-600">
                      {query ? "no matches" : "nothing tracked"}
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
