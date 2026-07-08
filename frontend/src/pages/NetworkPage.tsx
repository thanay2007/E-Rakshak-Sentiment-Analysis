import { Bot, Share2 } from "lucide-react";
import { useState } from "react";
import { BotChip, ThreatBadge } from "../components/Badges";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import NetworkGraph from "../components/NetworkGraph";
import { SkeletonChart, SkeletonRow } from "../components/Skeletons";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import type { NetNode } from "../services/api";

const WINDOWS = [
  { label: "24h", hours: 24 },
  { label: "48h", hours: 48 },
  { label: "7d", hours: 168 },
];

export default function NetworkPage() {
  const [hours, setHours] = useState(24);
  const [selected, setSelected] = useState<NetNode | null>(null);
  const { data, loading } = usePolling(() => api.network(hours), 60000, [hours]);
  const revealRef = useGsapReveal<HTMLDivElement>(data?.clusters.length ?? 0);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-bold text-slate-200">
            <Share2 size={18} className="text-accent" /> Network Analysis
          </h1>
          <p className="text-xs text-slate-500">
            account interaction graph · influence centrality · coordinated amplification detection
          </p>
        </div>
        <div className="flex gap-1.5">
          {WINDOWS.map((w) => (
            <button
              key={w.hours}
              onClick={() => setHours(w.hours)}
              className={`rounded-xl border px-3 py-1.5 font-mono text-xs transition-all ${
                hours === w.hours
                  ? "border-accent/50 bg-accent/10 text-accent"
                  : "border-white/10 text-slate-500 hover:text-slate-300"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <GlassCard className="p-2 xl:col-span-2">
          {loading && !data ? (
            <SkeletonChart h={560} />
          ) : data ? (
            <NetworkGraph nodes={data.nodes} links={data.links} onSelect={setSelected} />
          ) : null}
        </GlassCard>

        <div className="space-y-4">
          {selected && (
            <GlassCard className="border-accent/30 p-4">
              <SectionTitle title="Selected Account" />
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-200">{selected.label}</span>
                {selected.is_bot && <BotChip />}
              </div>
              <div className="mt-1 font-mono text-[11px] text-slate-500">
                @{selected.id} · {selected.platform} · {selected.followers.toLocaleString()} followers
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                {[
                  ["threat", Math.round(selected.threat)],
                  ["posts", selected.posts],
                  ["influence", (selected.influence * 100).toFixed(1)],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-xl bg-white/[0.04] p-2">
                    <div className="font-mono text-base font-bold text-slate-200">{v}</div>
                    <div className="text-[9px] uppercase tracking-widest text-slate-500">{k}</div>
                  </div>
                ))}
              </div>
            </GlassCard>
          )}

          <GlassCard className="p-4">
            <SectionTitle
              title="Coordinated Amplification"
              sub={data ? `${data.clusters.length} cluster(s) flagged in window` : undefined}
              right={<Bot size={15} className="text-threat-critical" />}
            />
            {loading && !data ? (
              <SkeletonRow n={3} />
            ) : (
              <div ref={revealRef} className="max-h-[520px] space-y-3 overflow-y-auto pr-1">
                {data?.clusters.map((c) => (
                  <div key={c.id} className="reveal-item rounded-xl border border-threat-critical/25 bg-threat-critical/[0.04] p-3">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-threat-critical">{c.id}</span>
                      <ThreatBadge label={c.label} />
                      <span className="ml-auto font-mono text-[11px] text-slate-400">
                        conf {(c.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.06]">
                      <div className="h-full rounded-full bg-threat-critical" style={{ width: `${c.confidence * 100}%` }} />
                    </div>
                    <ul className="mt-2 space-y-1 text-[11px] text-slate-400">
                      {c.why.map((w, i) => (
                        <li key={i} className="flex gap-1.5">
                          <span className="text-threat-critical">▸</span> {w}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-2 line-clamp-2 rounded-lg bg-black/20 p-2 text-[11px] italic text-slate-500">
                      “{c.sample_text}”
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {c.accounts.slice(0, 6).map((a) => (
                        <span key={a} className="rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                          @{a}
                        </span>
                      ))}
                      {c.accounts.length > 6 && (
                        <span className="font-mono text-[10px] text-slate-600">+{c.accounts.length - 6} more</span>
                      )}
                    </div>
                  </div>
                ))}
                {data?.clusters.length === 0 && (
                  <p className="py-6 text-center text-xs text-slate-500">
                    No coordinated behavior detected in this window.
                  </p>
                )}
              </div>
            )}
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
