import { ArrowRight, ExternalLink, Radio } from "lucide-react";
import { Link } from "react-router-dom";
import GlassCard, { SectionTitle } from "./GlassCard";
import { PlatformIcon } from "./Badges";
import EnglishGloss from "./EnglishGloss";
import { usePostDetail } from "./PostDetailProvider";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import { safeHref } from "../lib/safeUrl";

/** "Emerging but unverified" watch-list: posts spreading fast from a single,
 *  uncorroborated source — the window to catch a rumour before it goes viral. */
export default function EmergingPanel() {
  const { data } = usePolling(() => api.emerging(24), 45000);
  const { openPostId } = usePostDetail();
  const items = data?.items ?? [];

  return (
    <GlassCard className="border-amber-500/30 bg-amber-500/[0.02] p-5 shadow-xl">
      <SectionTitle
        title="Fast-Spreading Posts to Review"
        right={
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-[13px] font-bold text-amber-300">
              <Radio size={12} className="animate-pulse text-amber-400" />
              <span>EARLY WARNING</span>
              {(data?.total ?? items.length) > 0 && (
                <span className="ml-1 rounded-full bg-amber-500/30 px-1.5 py-0.2 font-mono text-xs text-amber-200">
                  {data?.total ?? items.length}
                </span>
              )}
            </div>
            <Link
              to="/app/unverified"
              className="inline-flex items-center gap-1 rounded-full border border-white/[0.1] px-3 py-1 text-[13px] font-semibold text-accent hover:bg-white/[0.04]"
            >
              View all <ArrowRight size={13} />
            </Link>
          </div>
        }
      />

      {items.length === 0 ? (
        <div className="py-8 text-center text-xs text-slate-400">
          No fast-spreading posts from a single source found in the last 24 hours.
        </div>
      ) : (
        <div className="max-h-[460px] overflow-y-auto pr-1.5 custom-scrollbar">
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
                className="flex h-full min-h-[215px] cursor-pointer flex-col rounded-2xl border border-amber-500/25 bg-base-800/90 dark:bg-base-950/80 p-4 backdrop-blur-md transition-all hover:border-amber-500/50 hover:bg-base-800/95 dark:hover:bg-base-950/95 shadow-md"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2 border-b border-white/[0.06] pb-2.5">
                    <div className="flex items-center gap-2 min-w-0">
                      <PlatformIcon platform={it.platform} size={18} />
                      <span className="truncate font-mono text-xs font-semibold text-slate-200">
                        @{it.author_handle}
                      </span>
                      {it.author_verified && <span className="text-xs text-sky-400 font-bold">✔</span>}
                    </div>
                  </div>

                  <p className="mt-2.5 line-clamp-2 break-words text-xs leading-relaxed text-slate-200">
                    {it.text}
                  </p>
                  <EnglishGloss id={it.post_id} text={it.text} translation={it.translation} language={it.language} className="mt-1.5 line-clamp-2 break-words" />

                  <div className="mt-2.5 space-y-1">
                    {it.reasons.slice(0, 2).map((r, i) => (
                      <div key={i} className="flex items-start gap-1.5 text-xs text-amber-200/80">
                        <span className="text-amber-400 font-bold">▸</span>
                        <span className="line-clamp-1">{r}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="mt-3 flex shrink-0 items-center justify-between gap-2 border-t border-white/[0.06] pt-2.5 text-[13px]">
                  <span className="truncate font-mono text-xs text-slate-400">
                    {it.source_count} single source
                  </span>
                  <div className="flex shrink-0 items-center gap-2.5">
                    {it.url ? (
                      <a
                        href={safeHref(it.url)}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex items-center gap-1 text-[13px] text-slate-400 hover:underline"
                      >
                        source <ExternalLink size={11} />
                      </a>
                    ) : (
                      <span className="text-[13px] text-slate-600" title="The platform gave no public link for this post">
                        no link
                      </span>
                    )}
                    <span className="text-[13px] font-semibold text-accent">full detail →</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </GlassCard>
  );
}

