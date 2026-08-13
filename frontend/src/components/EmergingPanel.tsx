import { ArrowRight, ExternalLink, Radio, TrendingUp } from "lucide-react";
import { Link } from "react-router-dom";
import GlassCard, { SectionTitle } from "./GlassCard";
import { PlatformIcon } from "./Badges";
import { usePostDetail } from "./PostDetailProvider";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import { safeHref } from "../lib/safeUrl";

/** Dashboard preview of the "emerging but unverified" queue.
 *
 *  Deliberately only the worst few: this is a glance on an already-dense
 *  dashboard, and the full queue — filterable and paged — is its own page.
 *  It asks the API for exactly those few rather than fetching the whole set
 *  and slicing in the browser. */
const PREVIEW = 6;

export default function EmergingPanel() {
  const { data } = usePolling(() => api.emerging({ hours: 24, limit: PREVIEW }), 45000);
  const { openPostId } = usePostDetail();
  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <GlassCard className="border-amber-500/30 bg-amber-500/[0.02] p-5 shadow-xl">
      <SectionTitle
        title="Emerging · Unverified Rumor Triage"
        right={
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-[11px] font-bold text-amber-300">
              <Radio size={12} className="animate-pulse text-amber-400" />
              <span>EARLY WARNING RADAR</span>
              {total > 0 && (
                <span className="ml-1 rounded-full bg-amber-500/30 px-1.5 py-0.2 font-mono text-[10px] text-amber-200">
                  {total}
                </span>
              )}
            </div>
            <Link
              to="/app/unverified"
              className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[11px] font-bold text-slate-300 transition-colors hover:border-accent/40 hover:text-accent"
            >
              View all <ArrowRight size={12} />
            </Link>
          </div>
        }
      />

      {items.length === 0 ? (
        <div className="py-8 text-center text-xs text-slate-400">
          No fast-spreading single-source posts detected in the last 24h window.
        </div>
      ) : (
        <div className="pr-1.5">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {items.map((it) => (
              <div
                key={it.post_id}
                role="button"
                tabIndex={0}
                onClick={() => openPostId(it.post_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    openPostId(it.post_id);
                  }
                }}
                className="flex h-[215px] cursor-pointer flex-col justify-between rounded-2xl border border-amber-500/25 bg-base-800/90 dark:bg-base-950/80 p-4 backdrop-blur-md transition-all hover:border-amber-500/50 hover:bg-base-800/95 dark:hover:bg-base-950/95 shadow-md"
              >
                <div>
                  <div className="flex items-center justify-between gap-2 border-b border-white/[0.06] pb-2.5">
                    <div className="flex items-center gap-2 min-w-0">
                      <PlatformIcon platform={it.platform} size={18} />
                      <span className="truncate font-mono text-xs font-semibold text-slate-200">
                        @{it.author_handle}
                      </span>
                      {it.author_verified && <span className="text-[10px] text-sky-400 font-bold">✔</span>}
                    </div>
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 font-mono text-[10.5px] font-black text-amber-300">
                      <TrendingUp size={11} /> spread {it.spread_score}
                    </span>
                  </div>

                  <p className="mt-2.5 line-clamp-2 text-xs leading-relaxed text-slate-200">
                    {it.text}
                  </p>

                  <div className="mt-2.5 space-y-1">
                    {it.reasons.slice(0, 2).map((r, i) => (
                      <div key={i} className="flex items-start gap-1.5 text-[10.5px] text-amber-200/80">
                        <span className="text-amber-400 font-bold">▸</span>
                        <span className="line-clamp-1">{r}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="flex items-center justify-between border-t border-white/[0.06] pt-2.5 text-[11px]">
                  <span className="font-mono text-[10.5px] text-slate-400">
                    {it.source_count} single source
                  </span>
                  <div className="flex items-center gap-2.5">
                    {it.url && (
                      <a
                        href={safeHref(it.url)}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex items-center gap-1 text-[11px] text-slate-400 hover:underline"
                      >
                        source <ExternalLink size={11} />
                      </a>
                    )}
                    <span className="text-[11px] font-semibold text-accent">full detail →</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
          {total > items.length && (
            <Link
              to="/app/unverified"
              className="mt-3 flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-amber-500/30 py-2.5 text-[12px] font-semibold text-amber-300/90 transition-colors hover:border-amber-500/60 hover:bg-amber-500/[0.06]"
            >
              {total - items.length} more in the triage queue <ArrowRight size={13} />
            </Link>
          )}
        </div>
      )}
    </GlassCard>
  );
}

