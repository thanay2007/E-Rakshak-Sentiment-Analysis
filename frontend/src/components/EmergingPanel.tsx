import { ExternalLink, Radio, TrendingUp } from "lucide-react";
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
    <GlassCard className="border-threat-high/25 p-4">
      <SectionTitle
        title="Emerging · Unverified"
        sub="high spread · single source · not yet corroborated — verify before it spreads"
        right={<Radio size={15} className="text-threat-high" />}
      />
      {items.length === 0 ? (
        <p className="py-6 text-center text-xs text-slate-500">
          No fast-spreading single-source posts right now.
        </p>
      ) : (
        <div className="space-y-2">
          {items.slice(0, 6).map((it) => (
            <div key={it.post_id} className="rounded-xl border border-threat-high/20 bg-threat-high/[0.03] p-3">
              <div className="flex items-center gap-2">
                <PlatformIcon platform={it.platform} size={18} />
                <span className="truncate font-mono text-[11px] text-slate-300">@{it.author_handle}</span>
                {it.author_verified && <span className="text-[9px] text-sky-400">✔</span>}
                <span className="ml-auto inline-flex items-center gap-1 rounded-md bg-threat-high/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-threat-high">
                  <TrendingUp size={10} /> spread {it.spread_score}
                </span>
                <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                  {it.source_count} source
                </span>
              </div>
              <p className="mt-1.5 line-clamp-2 text-[12px] text-slate-300">{it.text}</p>
              <ul className="mt-1.5 space-y-0.5">
                {it.reasons.map((r, i) => (
                  <li key={i} className="flex gap-1.5 text-[10.5px] text-slate-500">
                    <span className="text-threat-high">▸</span> {r}
                  </li>
                ))}
              </ul>
              {it.url && (
                <a href={safeHref(it.url)} target="_blank" rel="noreferrer"
                  className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-accent hover:underline">
                  view source <ExternalLink size={10} />
                </a>
              )}
            </div>
          ))}
          {data && data.count > 6 && (
            <p className="pt-1 text-center text-[10px] text-slate-600">
              +{data.count - 6} more flagged in the 24h window
            </p>
          )}
        </div>
      )}
    </GlassCard>
  );
}
