import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle, ExternalLink, Flag, Languages, ShieldCheck, UserRound, X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { SENTIMENT_COLORS, THREAT_COLORS, THREAT_SHORT } from "../data/constants";
import type { EvidenceReport, Post } from "../services/api";
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
  const [factCheck, setFactCheck] = useState<Post["fact_check"] | null>(null);
  const [checking, setChecking] = useState(false);
  const [dossier, setDossier] = useState<EvidenceReport | null>(null);
  const [dossierBusy, setDossierBusy] = useState(false);
  const [dossierError, setDossierError] = useState(false);

  useEffect(() => {
    setFactCheck(null);
    setEscalated(null);
    setDossier(null);
    setDossierError(false);
  }, [post?.id]);

  const report = dossier ?? (post?.evidence_report?.summary ? post.evidence_report : undefined);

  const generateDossier = async () => {
    if (!post || dossierBusy) return;
    setDossierBusy(true);
    setDossierError(false);
    try {
      setDossier(await api.evidenceReport(post.id));
    } catch {
      setDossierError(true);
    } finally {
      setDossierBusy(false);
    }
  };

  const fc = post ? factCheck ?? post.fact_check : undefined;
  const fakeSuspect =
    post?.threat_label === "Fake News" ||
    post?.llm_verification?.llm_threat_label === "Fake News";

  const runFactCheck = async () => {
    if (!post || checking) return;
    setChecking(true);
    try {
      setFactCheck(await api.factCheckPost(post.id));
    } catch {
      /* surfaced via button state */
    } finally {
      setChecking(false);
    }
  };

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

  // Portal to <body>: ancestors use CSS transforms (page transitions), which
  // would trap position:fixed and pin the drawer to the page top instead of
  // the viewport.
  return createPortal(
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
              {(post.media_urls?.length ?? 0) > 0 && (
                <div>
                  <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Attached media
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {post.media_urls!.map((m) => (
                      <a key={m} href={m} target="_blank" rel="noreferrer">
                        <img
                          src={m}
                          alt="post media"
                          className="max-h-40 rounded-xl border border-white/10 object-cover"
                          loading="lazy"
                        />
                      </a>
                    ))}
                  </div>
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

            {/* LLM second opinion (Groq verification layer) */}
            {post.llm_verification?.verdict && (
              <div
                className={`glass mt-4 border p-4 ${
                  post.llm_verification.overridden
                    ? "border-threat-high/40"
                    : "border-threat-neutral/30"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    LLM verification
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-[10px] font-bold ${
                      post.llm_verification.verdict === "agrees"
                        ? "bg-threat-neutral/15 text-threat-neutral"
                        : "bg-threat-high/15 text-threat-high"
                    }`}
                  >
                    <ShieldCheck size={10} />
                    {post.llm_verification.overridden
                      ? "OVERRIDDEN BY LLM"
                      : post.llm_verification.verdict.toUpperCase()}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                  <div className="rounded-lg bg-white/[0.03] p-2">
                    <div className="text-slate-500">LLM threat label</div>
                    <div className="font-mono text-slate-300">
                      {post.llm_verification.llm_threat_label}{" "}
                      ({((post.llm_verification.llm_confidence ?? 0) * 100).toFixed(0)}%)
                    </div>
                  </div>
                  <div className="rounded-lg bg-white/[0.03] p-2">
                    <div className="text-slate-500">LLM sentiment</div>
                    <div className="font-mono text-slate-300">{post.llm_verification.llm_sentiment}</div>
                  </div>
                </div>
                {(post.llm_verification.evidence?.length ?? 0) > 0 && (
                  <div className="mt-2 space-y-1">
                    <div className="text-[10px] text-slate-500">Verbatim evidence from the post:</div>
                    {post.llm_verification.evidence!.map((q) => (
                      <p key={q} className="rounded-lg border-l-2 border-threat-high/50 bg-white/[0.03] px-2 py-1 text-[11px] text-slate-300">
                        "{q}"
                      </p>
                    ))}
                  </div>
                )}
                {post.llm_verification.reason && (
                  <p className="mt-2 text-[11px] italic leading-relaxed text-slate-400">
                    "{post.llm_verification.reason}"
                  </p>
                )}
                <p className="mt-1 text-right font-mono text-[9.5px] text-slate-600">
                  {post.llm_verification.model}
                </p>
              </div>
            )}

            {/* Cross-source fact check (Google News corroboration) */}
            {fc?.checked ? (
              <div
                className={`glass mt-4 border p-4 ${
                  fc.verdict === "uncorroborated"
                    ? "border-threat-high/40"
                    : "border-threat-neutral/30"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Cross-source fact check
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-[10px] font-bold ${
                      fc.verdict === "corroborated"
                        ? "bg-threat-neutral/15 text-threat-neutral"
                        : "bg-threat-high/15 text-threat-high"
                    }`}
                  >
                    {fc.verdict?.toUpperCase()}
                  </span>
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-slate-400">{fc.note}</p>
                {fc.query && (
                  <p className="mt-1 text-[10px] text-slate-500">
                    Checked terms: <span className="font-mono text-slate-400">{fc.query}</span>
                  </p>
                )}
                {(fc.matches?.length ?? 0) > 0 && (
                  <div className="mt-2 space-y-1">
                    {fc.matches!.map((m) => (
                      <a
                        key={m.link}
                        href={m.link}
                        target="_blank"
                        rel="noreferrer"
                        className="block truncate text-[11px] text-sky-400 hover:underline"
                      >
                        {m.source ? `${m.source} — ` : ""}{m.title}
                      </a>
                    ))}
                  </div>
                )}
                <p className="mt-1 text-right font-mono text-[9.5px] text-slate-600">
                  Google News India
                </p>
              </div>
            ) : (
              fakeSuspect && (
                <button
                  onClick={runFactCheck}
                  disabled={checking}
                  className="glass mt-4 flex w-full items-center justify-center gap-2 border border-threat-high/30 p-3 text-xs font-semibold text-slate-300 hover:bg-white/[0.06] disabled:opacity-60"
                >
                  <ShieldCheck size={14} />
                  {checking
                    ? "Checking news sources..."
                    : "Run cross-source fact check (Google News)"}
                </button>
              )
            )}

            {/* Evidence dossier — analyst-grade detailed report */}
            {report ? (
              <div className="glass mt-4 border border-sky-500/25 p-4">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Evidence dossier
                  </span>
                  <span className="font-mono text-[10px] font-bold text-sky-400">
                    confidence {((report.confidence ?? 0) * 100).toFixed(0)}%
                  </span>
                </div>

                {report.summary && (
                  <p className="mt-2 text-[11.5px] leading-relaxed text-slate-300">{report.summary}</p>
                )}

                {(report.claims?.length ?? 0) > 0 && (
                  <div className="mt-3">
                    <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                      Claims assessed
                    </div>
                    <div className="space-y-2">
                      {report.claims!.map((c, i) => (
                        <div key={i} className="rounded-lg bg-white/[0.03] p-2">
                          <div className="flex items-start justify-between gap-2">
                            <span className="text-[11px] text-slate-300">{c.claim}</span>
                            <span
                              className={`shrink-0 rounded-md px-1.5 py-0.5 font-mono text-[9.5px] font-bold uppercase ${
                                c.assessment === "supported"
                                  ? "bg-threat-neutral/15 text-threat-neutral"
                                  : c.assessment === "contradicted"
                                    ? "bg-threat-critical/15 text-threat-critical"
                                    : "bg-threat-high/15 text-threat-high"
                              }`}
                            >
                              {c.assessment}
                            </span>
                          </div>
                          <p className="mt-1 text-[10.5px] leading-relaxed text-slate-500">
                            <span className="font-mono text-slate-600">[{c.type}]</span> {c.basis}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {(report.evidence_phrases?.length ?? 0) > 0 && (
                  <div className="mt-3">
                    <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                      Verbatim evidence
                    </div>
                    <div className="space-y-1.5">
                      {report.evidence_phrases!.map((e, i) => (
                        <div key={i} className="rounded-lg border-l-2 border-sky-500/40 bg-white/[0.03] px-2 py-1.5">
                          <p className="text-[11px] text-slate-200">"{e.quote}"</p>
                          <p className="mt-0.5 text-[10.5px] text-slate-500">{e.significance}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {report.corroboration?.verdict && (
                  <div className="mt-3 rounded-lg bg-white/[0.03] p-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                        Source corroboration
                      </span>
                      <span className="font-mono text-[10px] font-bold text-slate-300">
                        {report.corroboration.verdict.toUpperCase()}
                      </span>
                    </div>
                    {report.corroboration.explanation && (
                      <p className="mt-1 text-[10.5px] leading-relaxed text-slate-400">
                        {report.corroboration.explanation}
                      </p>
                    )}
                    {(report.corroboration.citations?.length ?? 0) > 0 && (
                      <div className="mt-1.5 space-y-1">
                        {report.corroboration.citations!.map((m) => (
                          <a
                            key={m.link}
                            href={m.link}
                            target="_blank"
                            rel="noreferrer"
                            className="block truncate text-[10.5px] text-sky-400 hover:underline"
                          >
                            {m.source ? `${m.source} — ` : ""}{m.title}
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="mt-3 grid gap-2 text-[10.5px]">
                  {report.account_assessment && (
                    <div className="rounded-lg bg-white/[0.03] p-2">
                      <div className="text-slate-500">Account assessment</div>
                      <p className="mt-0.5 leading-relaxed text-slate-400">{report.account_assessment}</p>
                    </div>
                  )}
                  {report.risk_assessment && (
                    <div className="rounded-lg bg-white/[0.03] p-2">
                      <div className="text-slate-500">Risk assessment</div>
                      <p className="mt-0.5 leading-relaxed text-slate-400">{report.risk_assessment}</p>
                    </div>
                  )}
                  {report.recommended_action && (
                    <div className="rounded-lg border border-sky-500/25 bg-sky-500/5 p-2">
                      <div className="text-slate-500">Recommended action</div>
                      <p className="mt-0.5 font-semibold leading-relaxed text-sky-300">
                        {report.recommended_action}
                      </p>
                    </div>
                  )}
                  {report.limitations && (
                    <div className="rounded-lg bg-white/[0.03] p-2">
                      <div className="text-slate-500">Limitations of this analysis</div>
                      <p className="mt-0.5 leading-relaxed text-slate-400">{report.limitations}</p>
                    </div>
                  )}
                </div>
                <p className="mt-2 text-right font-mono text-[9.5px] text-slate-600">
                  {report.model} · {report.generated_at?.slice(0, 19).replace("T", " ")} UTC
                </p>
              </div>
            ) : (
              <button
                onClick={generateDossier}
                disabled={dossierBusy}
                className="glass mt-4 flex w-full items-center justify-center gap-2 border border-sky-500/30 p-3 text-xs font-semibold text-slate-300 hover:bg-white/[0.06] disabled:opacity-60"
              >
                <ShieldCheck size={14} />
                {dossierBusy
                  ? "Compiling evidence dossier..."
                  : dossierError
                    ? "Failed — tap to retry evidence dossier"
                    : "Generate evidence dossier (detailed analysis)"}
              </button>
            )}

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
    </AnimatePresence>,
    document.body
  );
}
