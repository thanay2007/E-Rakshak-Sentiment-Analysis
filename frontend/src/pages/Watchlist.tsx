import { Eye, Hash, MapPin, Plus, Trash2, Type, UserRound } from "lucide-react";
import { useState } from "react";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import { SkeletonRow } from "../components/Skeletons";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";

const KIND_META: Record<string, { icon: typeof Type; color: string; label: string }> = {
  keyword: { icon: Type, color: "#14B8C4", label: "Keywords" },
  hashtag: { icon: Hash, color: "#A855F7", label: "Hashtags" },
  account: { icon: UserRound, color: "#F59E0B", label: "Accounts" },
  location: { icon: MapPin, color: "#10B981", label: "Locations" },
};

export default function Watchlist() {
  const { data, loading, refresh } = usePolling(() => api.watchlist(), 30000);
  const [kind, setKind] = useState("keyword");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const revealRef = useGsapReveal<HTMLDivElement>(data?.length ?? 0);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    await api.addWatch({ kind, value: value.trim(), note: note.trim() });
    setValue("");
    setNote("");
    refresh();
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-bold text-slate-200">
          <Eye size={18} className="text-accent" /> Watchlist
        </h1>
        <p className="text-xs text-slate-500">
          keywords, hashtags, accounts & geo-targets that steer live crawling — editable, applied on the next tick
        </p>
      </div>

      <GlassCard className="p-4">
        <form onSubmit={add} className="flex flex-wrap items-center gap-2">
          <select value={kind} onChange={(e) => setKind(e.target.value)} className="rounded-xl border border-white/[0.08] bg-base-800 px-2.5 py-2 text-xs text-slate-400">
            {Object.keys(KIND_META).map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Term to monitor (any language / script)"
            className="w-64 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:border-accent/40 focus:outline-none"
          />
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Analyst note (optional)"
            className="w-56 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:border-accent/40 focus:outline-none"
          />
          <button type="submit" className="glow-accent inline-flex items-center gap-1.5 rounded-xl border border-accent/50 bg-accent/15 px-4 py-2 text-xs font-bold text-accent hover:bg-accent hover:text-base-900">
            <Plus size={13} /> Add
          </button>
        </form>
      </GlassCard>

      {loading && !data ? (
        <SkeletonRow n={4} />
      ) : (
        <div ref={revealRef} className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {Object.entries(KIND_META).map(([k, meta]) => {
            const items = (data ?? []).filter((w) => w.kind === k);
            const Icon = meta.icon;
            return (
              <GlassCard key={k} className="reveal-item p-4">
                <SectionTitle
                  title={meta.label}
                  sub={`${items.length} tracked`}
                  right={<Icon size={15} style={{ color: meta.color }} />}
                />
                <div className="space-y-2">
                  {items.map((w) => (
                    <div key={w.id} className="flex items-center gap-2.5 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2">
                      <button
                        onClick={async () => { await api.updateWatch(w.id, { active: !w.active }); refresh(); }}
                        className={`h-4 w-7 rounded-full p-0.5 transition-colors ${w.active ? "bg-accent/70" : "bg-white/10"}`}
                        aria-label={w.active ? "Deactivate" : "Activate"}
                      >
                        <span className={`block h-3 w-3 rounded-full bg-white transition-transform ${w.active ? "translate-x-3" : ""}`} />
                      </button>
                      <span className={`text-[12.5px] font-medium ${w.active ? "text-slate-200" : "text-slate-600 line-through"}`}>
                        {w.value}
                      </span>
                      {w.note && <span className="truncate text-[10.5px] text-slate-600">— {w.note}</span>}
                      <button
                        onClick={async () => { await api.deleteWatch(w.id); refresh(); }}
                        className="ml-auto rounded-lg p-1 text-slate-600 hover:bg-threat-critical/15 hover:text-threat-critical"
                        aria-label="Delete"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  ))}
                  {items.length === 0 && <p className="py-3 text-center text-[11px] text-slate-600">nothing tracked</p>}
                </div>
              </GlassCard>
            );
          })}
        </div>
      )}
    </div>
  );
}
