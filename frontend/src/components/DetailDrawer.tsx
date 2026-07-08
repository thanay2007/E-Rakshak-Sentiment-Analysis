import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle, ExternalLink, Flag, Languages, ShieldCheck, UserRound, X,
} from "lucide-react";
import { useState } from "react";
import { SENTIMENT_COLORS, THREAT_COLORS, THREAT_SHORT } from "../data/constants";
import type { Post } from "../services/api";
import { api, API_BASE } from "../services/api";
import { BotChip, LanguageChip, PlatformIcon, ThreatBadge } from "./Badges";

/** Right slide-in drawer with the full NLP breakdown + Escalate action. */
export default function DetailDrawer({
  post,
  onClose,
}: {
  post: Post | null;
  onClose: () => void;
}) {
  const [escalated, setEscalated] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const escalate = async () => {
    if (!post || busy) return;
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/api/feed/${post.id}/escalate`, { method: "POST" });
      const data = await r.json();
      setEscalated(data.id);
    } catch {
      /* surfaced via disabled state */
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatePresence>
      {post && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className="fixed right-0 top-0 z-50 h-full w-full max-w-md overflow-y-auto border-l border-white/10 bg-base-800/95 p-5 backdrop-blur-2xl"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 28, stiffness: 260 }}
            aria-label="Post detail"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
                Intelligence Detail
              </h3>
              <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10">
                <X size={16} />
              </button>
            </div>

            {/* author card */}
            <div className="glass mt-4 flex items-center gap-3 p-3">
              <PlatformIcon platform={post.platform} size={34} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-semibold text-slate-200">
                    {post.author_name || post.author_handle}
                  </span>
                  {post.is_amplified && <BotChip />}
                </div>
                <div className="font-mono text-[11px] text-slate-500">
                  @{post.author_handle} · {post.author_followers.toLocaleString()} followers ·{" "}
                  {post.author_account_age_days ?? "?"}d old
                </div>
              </div>
              <UserRound size={16} className="text-slate-600" />
            </div>

            {/* original + translation */}
            <div className="mt-4 space-y-3">
              <div>
                <div className="mb-1 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  Original <LanguageChip language={post.language} mixed={post.code_mixed} />
                </div>
                <p className="glass p-3 text-[13.5px] leading-relaxed text-slate-200">{post.text}</p>
              </div>
              {post.translation && post.translation !== post.text && (
                <div>
                  <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    <Languages size={11} /> English translation
                  </div>
                  <p className="glass p-3 text-[13px] italic leading-relaxed text-slate-400">
                    {post.translation}
                  </p>
                </div>
              )}
            </div>

            {/* threat score */}
            <div className="glass mt-4 p-4">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  Composite threat score
                </span>
                <ThreatBadge label={post.threat_label} />
              </div>
              <div className="mt-2 flex items-end gap-3">
                <span
                  className="font-mono text-4xl font-bold"
                  style={{ color: THREAT_COLORS[post.threat_label] }}
                >
                  {Math.round(post.threat_score)}
                </span>
                <span className="pb-1 font-mono text-xs text-slate-500">/ 100</span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{
                    width: `${post.threat_score}%`,
                    backgroundColor: THREAT_COLORS[post.threat_label],
                  }}
                />
              </div>
            </div>

            {/* NLP breakdown */}
            <div className="glass mt-4 space-y-3 p-4">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                NLP breakdown
              </div>
              {post.class_probs &&
                Object.entries(post.class_probs)
                  .sort((a, b) => b[1] - a[1])
                  .map(([label, p]) => (
                    <div key={label} className="flex items-center gap-2">
                      <span className="w-24 shrink-0 text-[11px] text-slate-400">
                        {THREAT_SHORT[label] ?? label}
                      </span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${p * 100}%`, backgroundColor: THREAT_COLORS[label] }}
                        />
                      </div>
                      <span className="w-10 text-right font-mono text-[11px] text-slate-500">
                        {(p * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
              <div className="grid grid-cols-2 gap-2 pt-1 text-[11px]">
                <div className="rounded-lg bg-white/[0.03] p-2">
                  <div className="text-slate-500">Sentiment</div>
                  <div className="font-mono" style={{ color: SENTIMENT_COLORS[post.sentiment_label] }}>
                    {post.sentiment_label} ({post.sentiment_score.toFixed(2)})
                  </div>
                </div>
                <div className="rounded-lg bg-white/[0.03] p-2">
                  <div className="text-slate-500">Intent</div>
                  <div className="font-mono text-slate-300">{post.intent ?? "—"}</div>
                </div>
                <div className="rounded-lg bg-white/[0.03] p-2">
                  <div className="text-slate-500">Toxicity</div>
                  <div className="font-mono text-slate-300">
                    {((post.toxicity_score ?? 0) * 100).toFixed(0)}%
                  </div>
                </div>
                <div className="rounded-lg bg-white/[0.03] p-2">
                  <div className="text-slate-500">Code-mixing</div>
                  <div className="font-mono text-slate-300">{post.code_mixed ? "detected" : "no"}</div>
                </div>
              </div>
              {(post.hate_flags?.length ?? 0) > 0 && (
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {post.hate_flags!.map((f) => (
                    <span
                      key={f}
                      className="inline-flex items-center gap-1 rounded-md border border-threat-critical/40 bg-threat-critical/10 px-2 py-0.5 text-[10px] font-semibold text-threat-critical"
                    >
                      <AlertTriangle size={9} /> {f}
                    </span>
                  ))}
                </div>
              )}
              {(post.keywords?.length ?? 0) > 0 && (
                <div className="pt-1 text-[11px] text-slate-500">
                  Evidence terms:{" "}
                  <span className="font-mono text-slate-400">{post.keywords!.join(" · ")}</span>
                </div>
              )}
            </div>

            {/* actions */}
            <div className="mt-4 flex items-center gap-2">
              {post.url && (
                <a
                  href={post.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 px-3 py-2 text-xs font-medium text-slate-300 hover:bg-white/[0.06]"
                >
                  <ExternalLink size={13} /> Source
                </a>
              )}
              <button
                onClick={escalate}
                disabled={busy || !!escalated}
                className={`ml-auto inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-bold transition-all ${
                  escalated
                    ? "border border-threat-neutral/50 bg-threat-neutral/10 text-threat-neutral"
                    : "bg-threat-critical text-white hover:bg-red-600 glow-critical"
                }`}
              >
                {escalated ? (
                  <>
                    <ShieldCheck size={13} /> Escalated
                  </>
                ) : (
                  <>
                    <Flag size={13} /> {busy ? "Filing..." : "Escalate"}
                  </>
                )}
              </button>
            </div>
            {escalated && (
              <p className="mt-2 text-right font-mono text-[10px] text-slate-500">
                escalation report {escalated} filed → Reports
              </p>
            )}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
