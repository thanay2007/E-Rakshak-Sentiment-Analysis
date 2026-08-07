import { ChevronLeft, ChevronRight, Filter, FilterX, RefreshCw, Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
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

function FilterChip({ active, color, children, onClick }: {
  active: boolean; color?: string; children: React.ReactNode; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-xl border px-3 py-1.5 text-xs font-semibold transition-all shadow-sm ${
        active
          ? "shadow-md"
          : "border-white/[0.08] bg-white/[0.03] text-slate-400 hover:border-white/20 hover:bg-white/[0.06] hover:text-slate-200"
      }`}
      style={active ? {
        color: color ?? "#14B8C4",
        borderColor: `${color ?? "#14B8C4"}80`,
        backgroundColor: `${color ?? "#14B8C4"}22`,
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

  const removeParam = (k: string) => {
    setPage(1);
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete(k);
      return next;
    });
  };

  const urlQ = get("q");
  const [qDraft, setQDraft] = useState(urlQ);

  useEffect(() => setQDraft(urlQ), [urlQ]);

  useEffect(() => {
    if (qDraft === urlQ) return;
    const id = window.setTimeout(() => {
      setPage(1);
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (qDraft) next.set("q", qDraft);
          else next.delete("q");
          return next;
        },
        { replace: true }
      );
    }, 350);
    return () => window.clearTimeout(id);
  }, [qDraft, urlQ, setParams]);

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

  const { data, error, loading, refresh } = usePolling(() => api.feed(filters), 20000, [JSON.stringify(filters)]);
  const revealRef = useGsapReveal<HTMLDivElement>(data?.items[0]?.id ?? "");
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));

  const activeFiltersCount = [
    get("platform"),
    get("threat_level"),
    get("language"),
    get("location"),
    get("q"),
    get("min_score"),
    get("date_from"),
    get("date_to"),
  ].filter(Boolean).length;

  return (
    <div className="space-y-4">
      {/* filter bar */}
      <GlassCard className="space-y-3.5 border border-white/[0.08] p-4">
        {/* Row 1: Platforms & Threat Classes */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-300">
            <SlidersHorizontal size={13} className="text-accent" /> Filter By:
          </span>
          <div className="flex flex-wrap items-center gap-1.5">
            {PLATFORMS.map((p) => (
              <FilterChip
                key={p}
                active={get("platform").split(",").includes(p)}
                onClick={() => toggleCsv("platform", p)}
              >
                {p}
              </FilterChip>
            ))}
          </div>

          <span className="mx-1.5 hidden h-4 w-px bg-white/15 md:block" />

          <div className="flex flex-wrap items-center gap-1.5">
            {THREAT_LABELS.map((t) => (
              <FilterChip
                key={t}
                color={THREAT_COLORS[t]}
                active={get("threat_level").split(",").includes(t)}
                onClick={() => toggleCsv("threat_level", t)}
              >
                {THREAT_SHORT[t]}
              </FilterChip>
            ))}
          </div>
        </div>

        {/* Row 2: Search, Language, Geo, Score, Sorting */}
        <div className="flex flex-wrap items-center gap-2.5 pt-1 text-xs">
          <div className="relative min-w-[220px] flex-1">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={qDraft}
              onChange={(e) => setQDraft(e.target.value)}
              placeholder="Keyword / #hashtag / @handle"
              aria-label="Keyword search"
              className="w-full rounded-xl border border-white/[0.1] bg-white/[0.04] py-2 pl-9 pr-3 text-xs text-slate-100 placeholder:text-slate-500 focus:border-accent/60 focus:bg-white/[0.07] focus:outline-none"
            />
          </div>

          <select
            value={get("language")}
            onChange={(e) => setParam("language", e.target.value)}
            className="rounded-xl border border-white/[0.1] bg-base-800 py-2 pl-3 pr-8 text-xs text-slate-200 hover:border-white/20 focus:border-accent/60 focus:outline-none"
          >
            <option value="">All Languages</option>
            {LANGUAGES.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>

          <select
            value={get("location")}
            onChange={(e) => setParam("location", e.target.value)}
            className="rounded-xl border border-white/[0.1] bg-base-800 py-2 pl-3 pr-8 text-xs text-slate-200 hover:border-white/20 focus:border-accent/60 focus:outline-none"
          >
            <option value="">All Districts (Gujarat)</option>
            {CITIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>

          <div className="flex items-center gap-2 rounded-xl border border-white/[0.1] bg-base-800/80 px-3 py-1.5 text-xs text-slate-300">
            <span className="text-[11px] font-medium text-slate-400">Min Score:</span>
            <input
              type="range"
              min={0}
              max={80}
              step={5}
              value={get("min_score") || 0}
              onChange={(e) => setParam("min_score", e.target.value === "0" ? "" : e.target.value)}
              className="w-20 accent-[#14B8C4]"
            />
            <span className="w-6 font-mono font-bold text-accent">{get("min_score") || 0}</span>
          </div>

          <select
            value={get("sort") || "recent"}
            onChange={(e) => setParam("sort", e.target.value)}
            className="rounded-xl border border-white/[0.1] bg-base-800 py-2 pl-3 pr-8 text-xs text-slate-200 hover:border-white/20 focus:border-accent/60 focus:outline-none"
          >
            <option value="recent">Sort: Most Recent</option>
            <option value="score">Sort: Highest Threat</option>
            <option value="engagement">Sort: Most Shared</option>
          </select>

          {activeFiltersCount > 0 && (
            <button
              onClick={() => {
                setParams(new URLSearchParams());
                setPage(1);
              }}
              className="inline-flex items-center gap-1.5 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-300 hover:bg-red-500/20"
            >
              <FilterX size={13} /> Reset Filters ({activeFiltersCount})
            </button>
          )}
        </div>
      </GlassCard>

      {/* Results header & Pagination */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-1">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-base-950/70 px-3 py-1.5 font-mono text-xs font-bold text-slate-200 shadow-sm backdrop-blur-md">
            <span className="h-2 w-2 rounded-full bg-accent animate-pulse" />
            {data ? `${data.total.toLocaleString()} Matching Signals` : "Querying Pipeline…"}
          </span>
          <button
            onClick={() => void refresh()}
            className="flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-xs text-slate-300 hover:bg-white/[0.08] hover:text-white transition-all shadow-sm"
            title="Refresh feed"
          >
            <RefreshCw size={12} className={loading ? "animate-spin text-accent" : ""} />
            <span className="hidden sm:inline font-mono text-[11px]">Sync</span>
          </button>
        </div>

        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-slate-400">
            Page <strong className="text-slate-200">{page}</strong> / {totalPages}
          </span>
          <div className="flex items-center gap-1">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="rounded-xl border border-white/10 bg-white/[0.04] p-1.5 text-slate-300 disabled:opacity-30 hover:bg-white/[0.08] transition-all"
              aria-label="Previous page"
            >
              <ChevronLeft size={15} />
            </button>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="rounded-xl border border-white/10 bg-white/[0.04] p-1.5 text-slate-300 disabled:opacity-30 hover:bg-white/[0.08] transition-all"
              aria-label="Next page"
            >
              <ChevronRight size={15} />
            </button>
          </div>
        </div>
      </div>

      {error && !data ? (
        <GlassCard className="space-y-3 p-6 text-sm text-slate-300">
          <div className="font-semibold text-red-300">Could not load posts</div>
          <div className="text-xs text-slate-400">{error}</div>
          <button
            onClick={() => void refresh()}
            className="rounded-xl border border-accent/40 bg-accent/15 px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent/25"
          >
            Retry
          </button>
        </GlassCard>
      ) : loading && !data ? (
        <SkeletonRow n={8} />
      ) : (
        <div ref={revealRef} className="h-[calc(100vh-320px)] min-h-[500px] w-full rounded-2xl border border-white/[0.06] bg-base-950/40 p-2 backdrop-blur-md">
          {data?.items.length === 0 ? (
            <GlassCard className="p-12 text-center text-xs text-slate-400">
              No intelligence items match the current filter criteria. Broaden your search terms or reset filters.
            </GlassCard>
          ) : (
            <Virtuoso
              style={{ height: "100%", width: "100%" }}
              data={data?.items || []}
              itemContent={(_index, p) => (
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

