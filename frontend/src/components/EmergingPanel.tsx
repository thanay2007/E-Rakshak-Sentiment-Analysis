import { AlertTriangle, ExternalLink, Radio, ShieldAlert, TrendingUp } from "lucide-react";
import GlassCard, { SectionTitle } from "./GlassCard";
import { PlatformIcon } from "./Badges";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import { safeHref } from "../lib/safeUrl";

/** "Emerging but unverified" watch-list: posts spreading fast from a single,
 *  uncorroborated source — the window to catch a rumour before it goes viral. */
export default function EmergingPanel() {
  const { data } = usePolling(() => api.emerging(24), 45000);
  const items = data?.items ?? [];

  return (
    <GlassCard className="border-amber-500/30 bg-amber-500/[0.02] p-4.5 shadow-lg">
      <SectionTitle
        title="Emerging · Unverified Rumor Triage"
        sub="High-velocity single-source posts lacking official corroboration — verify before narrative viral lock-in"
        right={
          <div className="flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-bold text-amber-300">
            <Radio size={12} className="animate-pulse text-amber-400" />
            <span>EARLY WARNING RADAR</span>
          </div>
        }
      />

      {items.length === 0 ? (
        <div className="py-6 text-center text-xs text-slate-400">
          No fast-spreading single-source posts detected in the last 24h window.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 lg:grid-cols-3">
          {items.slice(0, 6).map((it) => (
            <div
              key={it.post_id}
              className="flex h-[200px] flex-col justify-between rounded-xl border border-amber-500/25 bg-base-950/70 p-3.5 backdrop-blur-md transition-all hover:border-amber-500/50 hover:bg-base-950/90"
            >
              <div>
                <div className="flex items-center justify-between gap-2 border-b border-white/[0.06] pb-2">
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

                <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-200">
                  {it.text}
                </p>

                <div className="mt-2 space-y-1">
                  {it.reasons.slice(0, 2).map((r, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-[10.5px] text-amber-200/80">
                      <span className="text-amber-400 font-bold">▸</span>
                      <span className="line-clamp-1">{r}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-between border-t border-white/[0.06] pt-2 text-[11px]">
                <span className="font-mono text-slate-400 text-[10.5px]">
                  {it.source_count} single source
                </span>
                {it.url && (
                  <a
                    href={safeHref(it.url)}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 font-semibold text-accent hover:underline text-[11px]"
                  >
                    inspect source <ExternalLink size={11} />
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {data && data.count > 6 && (
        <div className="mt-3 text-center text-xs font-semibold text-slate-400">
          +{data.count - 6} more unverified anomalies logged in 24h cycle
        </div>
      )}
    </GlassCard>
  );
}

