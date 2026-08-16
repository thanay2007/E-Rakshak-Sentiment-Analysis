import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle, ChevronLeft, ChevronRight, ExternalLink, Filter, Radio,
  RotateCcw, ShieldQuestion, TrendingUp, Users,
} from "lucide-react";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import { PlatformIcon, SentimentBadge } from "../components/Badges";
import { usePostDetail } from "../components/PostDetailProvider";
import { SkeletonRow } from "../components/Skeletons";
import { useUrlFilters } from "../hooks/useUrlFilters";
import { api } from "../services/api";
import type { EmergingData, EmergingItem } from "../services/api";
import { safeHref } from "../lib/safeUrl";

const WINDOWS = [6, 24, 72, 168];
const PAGE_SIZE = 24;

/** Priority bands. Lower than the old spread bands on purpose: priority is
 *  dominated by how alarming the claim is, and a post has to be genuinely
 *  hostile *and* rumour-shaped *and* travelling to clear 50. */
function priorityColor(v: number): string {
  if (v >= 50) return "#EF4444";
  if (v >= 35) return "#F59E0B";
  return "#A855F7";
}

function timeAgo(iso: string): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function Row({ it }: { it: EmergingItem }) {
  const { openPostId } = usePostDetail();
  const color = priorityColor(it.priority_score);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => openPostId(it.post_id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPostId(it.post_id); }
      }}
      className="cursor-pointer rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5 transition-all hover:border-amber-500/40 hover:bg-white/[0.04]"
    >
      <div className="flex items-start gap-3">
        <div className="grid shrink-0 place-items-center rounded-xl border px-2.5 py-1.5"
          style={{ borderColor: `${color}55`, backgroundColor: `${color}14` }}>
          <span className="font-mono text-lg font-black leading-none" style={{ color }}>
            {Math.round(it.priority_score)}
          </span>
          <span className="mt-0.5 text-[8.5px] uppercase tracking-wider text-slate-500">priority</span>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <PlatformIcon platform={it.platform} size={14} />
            <span className="font-mono text-[12px] font-semibold text-slate-200">@{it.author_handle}</span>
            {it.author_verified && <span className="text-[10px] font-bold text-sky-400">✔</span>}
            <SentimentBadge label={it.sentiment_label} />
            <span className="text-[11px] text-slate-500">
              {it.author_followers.toLocaleString()} followers
            </span>
            {it.location && <span className="text-[11px] text-slate-500">· {it.location}</span>}
            <span className="ml-auto text-[11px] text-slate-600">{timeAgo(it.created_at)}</span>
          </div>

          <p className="mt-1.5 line-clamp-2 text-[13px] leading-snug text-slate-200">{it.text}</p>

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
            {it.reasons.map((r, i) => (
              <span key={i} className="inline-flex items-start gap-1 text-[11px] text-amber-200/70">
                <span className="text-amber-400">▸</span>{r}
              </span>
            ))}
          </div>

          <div className="mt-2 flex items-center gap-3 border-t border-white/[0.05] pt-2 text-[11px]">
            <span className="inline-flex items-center gap-1 font-mono text-slate-500">
              <Users size={11} /> {it.source_count} source
            </span>
            <span className="font-mono text-slate-500">concern {Math.round(it.concern_score)}</span>
            {it.fact_check_verdict && (
              <span className="font-mono text-slate-500">news check: {it.fact_check_verdict}</span>
            )}
            {it.url && (
              <a href={safeHref(it.url)} target="_blank" rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="inline-flex items-center gap-1 text-slate-400 hover:underline">
                source <ExternalLink size={10} />
              </a>
            )}
            <span className="ml-auto font-semibold text-accent">open full detail →</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * The full "spreading but uncorroborated" queue.
 *
 * The dashboard panel shows the worst few; this is the page an analyst works
 * through. Every filter is URL-backed so a triage view can be handed to the
 * next shift as a link, and so the assistant can open this page already scoped
 * to a city or platform.
 */
export default function Unverified() {
  const { get, getNumber, set } = useUrlFilters();
  const hours = getNumber("hours", 24);
  const platform = get("platform", "");
  const location = get("location", "");
  const sentiment = get("sentiment", "");
  const minPriority = getNumber("min_priority", 0);
  const page = getNumber("page", 0);

  const [data, setData] = useState<EmergingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setErr(null);
    api.emerging({
      hours, platform, location, sentiment,
      min_priority: minPriority, limit: PAGE_SIZE, offset: page * PAGE_SIZE,
    })
      .then((d) => { if (alive) setData(d); })
      .catch((e) => { if (alive) setErr((e as Error).message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [hours, platform, location, sentiment, minPriority, page]);

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = Boolean(platform || location || sentiment || minPriority);

  const stats = useMemo(() => {
    const items = data?.items ?? [];
    return {
      critical: items.filter((i) => i.priority_score >= 50).length,
      rumourShaped: items.filter((i) => i.intent === "rumor" || i.intent === "call_to_action").length,
    };
  }, [data]);

  // Changing a filter must reset paging, or page 4 of a 2-page result is blank.
  const setFilter = (key: string, value: string | number) => {
    set(key, value);
    set("page", 0);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-2xl border border-amber-500/25 bg-base-950/80 p-4 shadow-xl backdrop-blur-xl md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-amber-500/40 bg-amber-500/15 text-amber-400">
            <ShieldQuestion size={20} />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-white sm:text-base">
              Unverified Claims · Check Before They Spread
            </h1>
            <p className="text-xs text-slate-400">
              Posts spreading fast that no other source has confirmed — check these before a rumour goes viral
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.03] p-1">
          {WINDOWS.map((w) => (
            <button key={w} onClick={() => setFilter("hours", w)}
              className={`rounded-lg px-3 py-1.5 font-mono text-xs font-bold transition-all ${
                hours === w ? "bg-accent text-base-950 shadow-md shadow-accent/20" : "text-slate-400 hover:text-slate-200"
              }`}>
              {w < 72 ? `${w}h` : `${w / 24}d`}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["In queue", total, "#F59E0B"],
          ["High priority (≥50)", stats.critical, "#EF4444"],
          ["Rumour-shaped on this page", stats.rumourShaped, "#A855F7"],
          ["Posts scanned", data?.scanned ?? 0, "#64748B"],
        ].map(([label, n, color]) => (
          <GlassCard key={label as string} className="p-3.5">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</div>
            <div className="mt-1 font-mono text-2xl font-black" style={{ color: color as string }}>
              {(n as number).toLocaleString()}
            </div>
          </GlassCard>
        ))}
      </div>

      <GlassCard className="p-3.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
            <Filter size={13} /> Filters
          </span>

          <select value={platform} onChange={(e) => setFilter("platform", e.target.value)}
            className="rounded-xl border border-white/[0.1] bg-base-800 py-1.5 pl-3 pr-8 text-xs text-slate-200 focus:border-accent/60 focus:outline-none">
            <option value="">All platforms</option>
            {(data?.platforms ?? []).map((p) => <option key={p} value={p}>{p}</option>)}
          </select>

          <select value={location} onChange={(e) => setFilter("location", e.target.value)}
            className="rounded-xl border border-white/[0.1] bg-base-800 py-1.5 pl-3 pr-8 text-xs text-slate-200 focus:border-accent/60 focus:outline-none">
            <option value="">All locations</option>
            {(data?.locations ?? []).map((l) => <option key={l} value={l}>{l}</option>)}
          </select>

          <select value={sentiment} onChange={(e) => setFilter("sentiment", e.target.value)}
            className="rounded-xl border border-white/[0.1] bg-base-800 py-1.5 pl-3 pr-8 text-xs text-slate-200 focus:border-accent/60 focus:outline-none">
            <option value="">Any sentiment</option>
            <option value="negative">Negative</option>
            <option value="neutral">Neutral</option>
            <option value="positive">Positive</option>
          </select>

          <label className="flex items-center gap-2 text-[11px] text-slate-400">
            <TrendingUp size={12} /> min priority
            <input type="range" min={0} max={80} step={5} value={minPriority}
              onChange={(e) => setFilter("min_priority", Number(e.target.value))}
              className="w-24 accent-[#14B8C4]" />
            <span className="w-6 font-mono text-slate-200">{minPriority}</span>
          </label>

          {filtered && (
            <button
              onClick={() => {
                set("platform", ""); set("location", ""); set("sentiment", "");
                set("min_priority", 0); set("page", 0);
              }}
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold text-slate-300 hover:text-accent">
              <RotateCcw size={12} /> Clear
            </button>
          )}

          <span className="ml-auto text-[11px] text-slate-500">
            showing {data?.count ?? 0} of {total.toLocaleString()}
          </span>
        </div>
      </GlassCard>

      {err && (
        <GlassCard className="flex items-center gap-2 p-4 text-sm text-red-400">
          <AlertTriangle size={15} /> {err}
        </GlassCard>
      )}

      {loading && !data ? <SkeletonRow n={6} /> : (
        <>
          {(data?.items.length ?? 0) === 0 ? (
            <GlassCard className="p-10 text-center">
              <Radio size={22} className="mx-auto mb-2 text-slate-600" />
              <p className="text-sm text-slate-400">
                Nothing uncorroborated is spreading in this window.
              </p>
              <p className="mt-1 text-xs text-slate-600">
                {data?.scanned
                  ? `${data.scanned.toLocaleString()} posts were checked${filtered ? " — try clearing the filters" : ""}.`
                  : "No posts in this window at all."}
              </p>
            </GlassCard>
          ) : (
            <div className="space-y-2">
              {data?.items.map((it) => <Row key={it.post_id} it={it} />)}
            </div>
          )}

          {/* Why the queue is short. Without this, strict filtering is
              indistinguishable from a detector that silently stopped. */}
          {data && Boolean(data.dropped?.established || data.dropped?.low_concern) && (
            <p className="px-1 pt-1 text-[11px] leading-relaxed text-slate-600">
              Of {data.scanned.toLocaleString()} posts scanned:{" "}
              {(data.dropped.established ?? 0).toLocaleString()} came from established channels
              (verified, 100k+ followers, or posting at news-desk volume — they corroborate claims
              rather than start them),{" "}
              {(data.dropped.not_a_claim ?? 0).toLocaleString()} asserted nothing checkable
              (praise, reel captions, walls of hashtags),{" "}
              {(data.dropped.low_concern ?? 0).toLocaleString()} were not alarming enough to triage,
              and {(data.dropped.corroborated ?? 0).toLocaleString()} were already corroborated
              by another account or by the news index.
            </p>
          )}

          {pages > 1 && (
            <div className="flex items-center justify-center gap-3 pt-1">
              <button disabled={page <= 0} onClick={() => set("page", page - 1)}
                className="inline-flex items-center gap-1 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-semibold text-slate-300 disabled:opacity-30 hover:text-accent">
                <ChevronLeft size={13} /> Previous
              </button>
              <span className="font-mono text-xs text-slate-500">page {page + 1} of {pages}</span>
              <button disabled={page + 1 >= pages} onClick={() => set("page", page + 1)}
                className="inline-flex items-center gap-1 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-semibold text-slate-300 disabled:opacity-30 hover:text-accent">
                Next <ChevronRight size={13} />
              </button>
            </div>
          )}
        </>
      )}

      <p className="px-1 text-[11px] leading-relaxed text-slate-600">
        “Unverified” means no second account in the window posted the same claim and no news index
        corroborated it — not that the claim is false. It is a queue to check, not a finding.
      </p>
    </div>
  );
}
