import { ChevronLeft, ChevronRight, FilterX, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Virtuoso } from "react-virtuoso";
import DetailDrawer from "../components/DetailDrawer";
import FeedItemCard from "../components/FeedItemCard";
import GlassCard from "../components/GlassCard";
import { SkeletonRow } from "../components/Skeletons";
import { LANGUAGES, PLATFORMS, THREAT_COLORS, THREAT_LABELS, THREAT_SHORT } from "../data/constants";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import type { Post } from "../services/api";

const CITIES = ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Gandhinagar", "Bhavnagar", "Jamnagar", "Junagadh"];
const PAGE_SIZE = 20;

function Chip({ active, color, children, onClick }: {
  active: boolean; color?: string; children: React.ReactNode; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-2.5 py-1 text-[11px] font-medium transition-all ${
        active ? "" : "border-white/10 text-slate-500 hover:border-white/25 hover:text-slate-300"
      }`}
      style={active ? {
        color: color ?? "#14B8C4",
        borderColor: `${color ?? "#14B8C4"}66`,
        backgroundColor: `${color ?? "#14B8C4"}14`,
      } : undefined}
    >
      {children}
    </button>
  );
}

export default function ThreatFeed() {
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState<Post | null>(null);
  const [page, setPage] = useState(1);

  const get = (k: string) => params.get(k) ?? "";
  const setParam = (k: string, v: string) => {
    setPage(1);
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (v) next.set(k, v);
      else next.delete(k);
      return next;
    });
  };
  const toggleCsv = (k: string, v: string) => {
    const cur = get(k) ? get(k).split(",") : [];
    const next = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v];
    setParam(k, next.join(","));
  };

  const filters = useMemo(
    () => ({
      platform: get("platform") || undefined,
      language: get("language") || undefined,
      threat_level: get("threat_level") || undefined,
      location: get("location") || undefined,
      q: get("q") || undefined,
      min_score: get("min_score") ? Number(get("min_score")) : undefined,
      date_from: get("date_from") || undefined,
      date_to: get("date_to") || undefined,
      sort: (get("sort") || "recent") as "recent" | "score" | "engagement",
      page,
      page_size: PAGE_SIZE,
    }),
    [params, page] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const { data, loading } = usePolling(() => api.feed(filters), 20000, [JSON.stringify(filters)]);
  const revealRef = useGsapReveal<HTMLDivElement>(data?.items[0]?.id ?? "");
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));

  return (
    <div className="space-y-4">
      {/* filter bar */}
      <GlassCard className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">
            <SlidersHorizontal size={12} /> Filters
          </span>
          {PLATFORMS.map((p) => (
            <Chip key={p} active={get("platform").split(",").includes(p)} onClick={() => toggleCsv("platform", p)}>
              {p}
            </Chip>
          ))}
          <span className="mx-1 h-4 w-px bg-white/10" />
          {THREAT_LABELS.map((t) => (
            <Chip key={t} color={THREAT_COLORS[t]} active={get("threat_level").split(",").includes(t)} onClick={() => toggleCsv("threat_level", t)}>
              {THREAT_SHORT[t]}
            </Chip>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <input
            value={get("q")}
            onChange={(e) => setParam("q", e.target.value)}
            placeholder="Keyword / #hashtag / @handle"
            className="w-52 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-accent/40 focus:outline-none"
          />
          <select value={get("language")} onChange={(e) => setParam("language", e.target.value)} className="rounded-xl border border-white/[0.08] bg-base-800 pl-2 pr-8 py-1.5 text-slate-400">
            <option value="">Language</option>
            {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
          <select value={get("location")} onChange={(e) => setParam("location", e.target.value)} className="rounded-xl border border-white/[0.08] bg-base-800 pl-2 pr-8 py-1.5 text-slate-400">
            <option value="">Geo watchlist</option>
            {CITIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <label className="flex items-center gap-2 text-slate-500">
            min score
            <input
              type="range" min={0} max={80} step={5}
              value={get("min_score") || 0}
              onChange={(e) => setParam("min_score", e.target.value === "0" ? "" : e.target.value)}
              className="w-24 accent-[#14B8C4]"
            />
            <span className="w-6 font-mono text-slate-300">{get("min_score") || 0}</span>
          </label>
          <input type="datetime-local" value={get("date_from")} onChange={(e) => setParam("date_from", e.target.value)} className="rounded-xl border border-white/[0.08] bg-base-800 px-2 py-1.5 text-slate-400" aria-label="From" />
          <input type="datetime-local" value={get("date_to")} onChange={(e) => setParam("date_to", e.target.value)} className="rounded-xl border border-white/[0.08] bg-base-800 px-2 py-1.5 text-slate-400" aria-label="To" />
          <select value={get("sort") || "recent"} onChange={(e) => setParam("sort", e.target.value)} className="rounded-xl border border-white/[0.08] bg-base-800 pl-2 pr-8 py-1.5 text-slate-400">
            <option value="recent">Most recent</option>
            <option value="score">Highest threat</option>
            <option value="engagement">Most shared</option>
          </select>
          <button
            onClick={() => { setParams(new URLSearchParams()); setPage(1); }}
            className="ml-auto inline-flex items-center gap-1 rounded-xl border border-white/10 px-2.5 py-1.5 text-slate-500 hover:text-slate-300"
          >
            <FilterX size={12} /> Clear
          </button>
        </div>
      </GlassCard>

      {/* results */}
      <div className="flex items-center justify-between px-1">
        <span className="font-mono text-[11px] text-slate-500">
          {data ? `${data.total.toLocaleString()} matching posts` : "querying…"}
        </span>
        <div className="flex items-center gap-2">
          <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="rounded-lg border border-white/10 p-1.5 text-slate-400 disabled:opacity-30 hover:bg-white/[0.06]" aria-label="Previous page">
            <ChevronLeft size={14} />
          </button>
          <span className="font-mono text-[11px] text-slate-500">{page} / {totalPages}</span>
          <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)} className="rounded-lg border border-white/10 p-1.5 text-slate-400 disabled:opacity-30 hover:bg-white/[0.06]" aria-label="Next page">
            <ChevronRight size={14} />
          </button>
        </div>
      </div>

      {loading && !data ? (
        <SkeletonRow n={8} />
      ) : (
        <div ref={revealRef} className="h-[70vh] w-full">
          {data?.items.length === 0 ? (
            <GlassCard className="p-10 text-center text-sm text-slate-500">
              No posts match the current filters.
            </GlassCard>
          ) : (
            <Virtuoso
              style={{ height: '100%', width: '100%' }}
              data={data?.items || []}
              itemContent={(index, p) => (
                <div className="pb-2.5 pr-1">
                  <FeedItemCard post={p} onOpen={setSelected} />
                </div>
              )}
            />
          )}
        </div>
      )}

      <DetailDrawer post={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
