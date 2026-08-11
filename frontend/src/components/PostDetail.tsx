import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle, BookOpen, Brain, Building2, ExternalLink, Flag, Gauge,
  Languages, Newspaper, ScrollText, ShieldCheck, Sparkles, UserRound, X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  concernBand, concernColor, SENTIMENT_TEXT, sentimentColor,
} from "../data/constants";
import type { EvidenceReport, EvidenceSource, Post } from "../services/api";
import { api, API_BASE } from "../services/api";
import { BotChip, LanguageChip, PlatformIcon, SentimentBadge } from "./Badges";
import { PostMediaGrid } from "./PostMedia";
import { safeHref } from "../lib/safeUrl";

/** Icon per evidence-source kind, so the provenance list scans at a glance. */
const KIND_ICON: Record<string, typeof Brain> = {
  model: Brain,
  llm: Sparkles,
  context: ScrollText,
  metadata: Building2,
  score: Gauge,
  news: Newspaper,
};

function Section({
  title, icon: Icon, right, accent, children,
}: {
  title: string;
  icon?: typeof Brain;
  right?: React.ReactNode;
  accent?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="glass mt-4 p-4"
      style={accent ? { borderColor: `${accent}40`, borderWidth: 1 } : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          {Icon && <Icon size={11} />} {title}
        </span>
        {right}
      </div>
      {children}
    </div>
  );
}

/** "Where this verdict came from" — one card per contributing source. */
function EvidenceTrail({ sources }: { sources: EvidenceSource[] }) {
  return (
    <div className="mt-2 space-y-2">
      {sources.map((e, i) => {
        const Icon = KIND_ICON[e.kind] ?? BookOpen;
        return (
          <div key={`${e.source}-${i}`} className="rounded-lg bg-white/[0.03] p-2.5">
            <div className="flex items-start justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-slate-200">
                <Icon size={11} className="shrink-0 text-slate-400" />
                {e.source}
              </span>
              {e.verdict && (
                <span className="shrink-0 rounded-md bg-white/[0.06] px-1.5 py-0.5 font-mono text-[9.5px] text-slate-300">
                  {e.verdict}
                </span>
              )}
            </div>
            {e.detail && (
              <p className="mt-0.5 text-[10.5px] leading-relaxed text-slate-500">{e.detail}</p>
            )}
            {(e.items?.length ?? 0) > 0 && (
              <ul className="mt-1.5 space-y-0.5">
                {e.items!.map((it, j) => (
                  <li key={j} className="flex gap-1.5 text-[10.5px] leading-relaxed text-slate-400">
                    <span className="text-slate-600">·</span>
                    <span>{it}</span>
                  </li>
                ))}
              </ul>
            )}
            {(e.links?.length ?? 0) > 0 && (
              <div className="mt-1.5 space-y-0.5">
                {e.links!.map((m) => (
                  <a
                    key={m.link}
                    href={safeHref(m.link)}
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
        );
      })}
    </div>
  );
}

/**
 * The full record for one post: what it says, what it says in English, what the
 * models decided, and every source behind that decision.
 *
 * Rendered once by PostDetailProvider and opened from anywhere via
 * `usePostDetail()`.
 */
export default function PostDetail({
  post, loading = false, error = null, onClose,
}: {
  post: Post | null;
  loading?: boolean;
  error?: string | null;
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

  const asideRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Modal behaviour: Escape to close, Tab trapped inside, background scroll
  // locked, and focus returned to whatever opened the drawer.
  const open = !!post || loading || !!error;
  useEffect(() => {
    if (!open) return;
    const restoreTo = document.activeElement as HTMLElement | null;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const focusables = asideRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (!focusables?.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const raf = window.requestAnimationFrame(() => asideRef.current?.focus());

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevOverflow;
      window.cancelAnimationFrame(raf);
      restoreTo?.focus?.();
    };
  }, [open]);

  const report = dossier ?? (post?.evidence_report?.summary ? post.evidence_report : undefined);
  const consensus = post?.sentiment_consensus;
  const fc = post ? factCheck ?? post.fact_check : undefined;

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
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            aria-hidden="true"
          />
          <motion.aside
            ref={asideRef}
            className="fixed right-0 top-0 z-50 h-full w-full max-w-md overflow-y-auto border-l border-white/10 bg-base-800/95 p-5 backdrop-blur-2xl focus:outline-none"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 28, stiffness: 260 }}
            role="dialog"
            aria-modal="true"
            aria-label="Post detail"
            tabIndex={-1}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
                Post detail
              </h3>
              <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10">
                <X size={16} />
              </button>
            </div>

            {loading && (
              <div className="mt-6 space-y-3">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="h-20 animate-pulse rounded-xl bg-white/[0.05]" />
                ))}
                <p className="text-center text-[11px] text-slate-500">Loading the post record…</p>
              </div>
            )}

            {error && !post && (
              <p className="glass mt-6 p-4 text-[12px] leading-relaxed text-slate-400">{error}</p>
            )}

            {post && (
              <>
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
                      {post.author_verified && " · verified"}
                    </div>
                  </div>
                  <UserRound size={16} className="text-slate-600" />
                </div>

                {/* ── the tag and the score ─────────────────────────────── */}
                <div className="glass mt-4 p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                      Sentiment tag
                    </span>
                    <SentimentBadge label={post.sentiment_label} size="lg" />
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                    <div className="rounded-lg bg-white/[0.03] p-2">
                      <div className="text-slate-500">Polarity</div>
                      <div
                        className="font-mono text-lg font-bold"
                        style={{ color: sentimentColor(post.sentiment_label) }}
                      >
                        {post.sentiment_score > 0 ? "+" : ""}
                        {post.sentiment_score.toFixed(2)}
                      </div>
                      <div className="text-[9.5px] text-slate-600">−1 negative … +1 positive</div>
                    </div>
                    <div className="rounded-lg bg-white/[0.03] p-2">
                      <div className="text-slate-500">Model confidence</div>
                      <div className="font-mono text-lg font-bold text-slate-200">
                        {((post.sentiment_confidence ?? consensus?.confidence ?? 0) * 100).toFixed(0)}%
                      </div>
                      <div className="text-[9.5px] text-slate-600">
                        {consensus?.agreement ? `${consensus.agreement} models agreed` : "—"}
                      </div>
                    </div>
                  </div>

                  <div className="mt-3">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                        Concern score
                      </span>
                      <span
                        className="font-mono text-[10px] font-bold uppercase"
                        style={{ color: concernColor(post.concern_score) }}
                      >
                        {concernBand(post.concern_score)}
                      </span>
                    </div>
                    <div className="mt-1 flex items-end gap-3">
                      <span
                        className="font-mono text-4xl font-bold"
                        style={{ color: concernColor(post.concern_score) }}
                      >
                        {Math.round(post.concern_score)}
                      </span>
                      <span className="pb-1 font-mono text-xs text-slate-500">/ 100</span>
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                      <div
                        className="h-full rounded-full transition-all duration-700"
                        style={{
                          width: `${post.concern_score}%`,
                          backgroundColor: concernColor(post.concern_score),
                        }}
                      />
                    </div>
                  </div>

                  {/* how the score was built */}
                  {(consensus?.score_breakdown?.length ?? 0) > 0 && (
                    <div className="mt-3 space-y-1.5 border-t border-white/[0.06] pt-3">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                        How this score was built
                      </div>
                      {consensus!.score_breakdown!.map((p) => (
                        <div key={p.factor} className="flex items-center gap-2" title={p.detail}>
                          <span className="w-28 shrink-0 text-[10.5px] text-slate-400">
                            {p.factor}
                          </span>
                          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
                            <div
                              className="h-full rounded-full bg-accent/70"
                              style={{ width: `${Math.min(100, p.points)}%` }}
                            />
                          </div>
                          <span className="w-14 text-right font-mono text-[10.5px] text-slate-500">
                            {p.points.toFixed(1)} pts
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* ── original + translation ────────────────────────────── */}
                <div className="mt-4 space-y-3">
                  <div>
                    <div className="mb-1 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                      Original <LanguageChip language={post.language} mixed={post.code_mixed} />
                    </div>
                    <p className="glass p-3 text-[13.5px] leading-relaxed text-slate-200">{post.text}</p>
                  </div>
                  {post.translation && post.translation !== post.text ? (
                    <div>
                      <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                        <Languages size={11} /> English translation
                      </div>
                      <p className="glass p-3 text-[13px] italic leading-relaxed text-slate-400">
                        {post.translation}
                      </p>
                    </div>
                  ) : (
                    post.language !== "English" && (
                      <p className="text-[10.5px] italic text-slate-600">
                        No English translation on record for this post yet — run
                        “Backfill translations” from Settings to fill the gap.
                      </p>
                    )
                  )}
                  {(post.media_urls?.length ?? 0) > 0 && (
                    <div>
                      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                        Attached media ({post.media_urls!.length})
                      </div>
                      <PostMediaGrid urls={post.media_urls!} maxHeight={160} />
                    </div>
                  )}
                </div>

                {/* ── 3-model consensus + Groq final check ──────────────── */}
                {(consensus?.votes?.length ?? 0) > 0 && (
                  <Section
                    title="3-model consensus"
                    icon={Brain}
                    accent="#38BDF8"
                    right={
                      <span className="font-mono text-[10px] text-slate-400">
                        agreement {consensus!.agreement}
                      </span>
                    }
                  >
                    <div className="mt-2 space-y-1.5">
                      {consensus!.votes!.map((v) => {
                        const isWinner = v.label === consensus!.label;
                        const c = sentimentColor(v.label);
                        return (
                          <div key={v.model} className="flex items-center gap-2">
                            <span className="w-20 shrink-0 font-mono text-[10.5px] capitalize text-slate-400">
                              {v.model}
                            </span>
                            <span
                              className="w-14 shrink-0 text-[11px] font-semibold capitalize"
                              style={{ color: c }}
                            >
                              {v.label}
                            </span>
                            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
                              <div
                                className="h-full rounded-full"
                                style={{ width: `${v.confidence * 100}%`, backgroundColor: c }}
                              />
                            </div>
                            <span className="w-9 text-right font-mono text-[10.5px] text-slate-500">
                              {(v.confidence * 100).toFixed(0)}%
                            </span>
                            {isWinner && <span className="text-[10px] text-accent">✓</span>}
                          </div>
                        );
                      })}
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-2 rounded-lg bg-white/[0.03] px-2 py-1.5">
                      <span className="shrink-0 text-[10.5px] text-slate-500">Chosen</span>
                      <span
                        className="text-right font-mono text-[10.5px] font-semibold capitalize"
                        style={{ color: sentimentColor(consensus!.label) }}
                      >
                        {consensus!.label} · {consensus!.chosen_by}
                      </span>
                    </div>

                    {(consensus!.context_adjustments?.length ?? 0) > 0 && (
                      <div className="mt-2 space-y-1">
                        <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                          Context adjustments (confidence only)
                        </div>
                        {consensus!.context_adjustments!.map((a, i) => (
                          <div key={i} className="rounded-lg bg-white/[0.03] px-2 py-1.5">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[10.5px] font-semibold text-slate-300">
                                {a.factor}
                              </span>
                              <span
                                className={`font-mono text-[10px] font-bold ${
                                  a.delta >= 0 ? "text-threat-neutral" : "text-threat-high"
                                }`}
                              >
                                {a.delta >= 0 ? "+" : ""}{a.delta.toFixed(2)}
                              </span>
                            </div>
                            <p className="mt-0.5 text-[10px] leading-relaxed text-slate-500">
                              {a.reason}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}

                    {consensus!.groq_check && (
                      <div
                        className={`mt-2 rounded-lg px-2 py-2 ${
                          consensus!.groq_check.overrode
                            ? "bg-threat-high/10"
                            : consensus!.groq_check.agrees
                              ? "bg-threat-neutral/10"
                              : "bg-white/[0.04]"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="inline-flex items-center gap-1 text-[10.5px] font-semibold text-slate-200">
                            <Sparkles size={10} /> Groq final check
                          </span>
                          <span className="font-mono text-[10px] font-bold text-slate-300">
                            {consensus!.groq_check.label} ·{" "}
                            {((consensus!.groq_check.confidence ?? 0) * 100).toFixed(0)}%
                          </span>
                        </div>
                        <p className="mt-0.5 text-[10px] font-semibold text-slate-400">
                          {consensus!.groq_check.overrode
                            ? "Overrode the model consensus"
                            : consensus!.groq_check.agrees
                              ? "Agrees with the models"
                              : "Dissents — not confident enough to override"}
                        </p>
                        {consensus!.groq_check.reason && (
                          <p className="mt-1 text-[10px] italic leading-relaxed text-slate-500">
                            “{consensus!.groq_check.reason}”
                          </p>
                        )}
                      </div>
                    )}
                  </Section>
                )}

                {/* ── evidence provenance ───────────────────────────────── */}
                {(consensus?.evidence?.length ?? 0) > 0 && (
                  <Section
                    title="Evidence — where this came from"
                    icon={BookOpen}
                    accent="#F59E0B"
                    right={
                      <span className="font-mono text-[10px] text-slate-400">
                        {consensus!.evidence!.length} sources
                      </span>
                    }
                  >
                    <EvidenceTrail sources={consensus!.evidence!} />
                  </Section>
                )}

                {/* ── other signals ─────────────────────────────────────── */}
                <Section title="Other signals">
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
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
                      <div className="font-mono text-slate-300">
                        {post.code_mixed ? "detected" : "no"}
                      </div>
                    </div>
                    <div className="rounded-lg bg-white/[0.03] p-2">
                      <div className="text-slate-500">Location</div>
                      <div className="font-mono text-slate-300">{post.location || "—"}</div>
                    </div>
                  </div>
                  {(post.hate_flags?.length ?? 0) > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
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
                    <div className="mt-2 text-[11px] text-slate-500">
                      Matched terms:{" "}
                      <span className="font-mono text-slate-400">{post.keywords!.join(" · ")}</span>
                    </div>
                  )}
                </Section>

                {/* ── news corroboration ────────────────────────────────── */}
                {fc?.checked ? (
                  <Section
                    title="News corroboration"
                    icon={Newspaper}
                    accent={fc.verdict === "uncorroborated" ? "#EA580C" : "#059669"}
                    right={
                      <span
                        className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-[10px] font-bold ${
                          fc.verdict === "corroborated"
                            ? "bg-threat-neutral/15 text-threat-neutral"
                            : "bg-threat-high/15 text-threat-high"
                        }`}
                      >
                        {fc.verdict?.toUpperCase()}
                      </span>
                    }
                  >
                    <p className="mt-2 text-[11px] leading-relaxed text-slate-400">{fc.note}</p>
                    {fc.query && (
                      <p className="mt-1 text-[10px] text-slate-500">
                        Searched terms:{" "}
                        <span className="font-mono text-slate-400">{fc.query}</span>
                      </p>
                    )}
                    {(fc.attempted?.length ?? 0) > 0 && (
                      <p className="mt-1 text-[10px] text-slate-500">
                        Queried:{" "}
                        {fc.attempted!.map((a) => (
                          <span
                            key={a}
                            className={`mr-1 inline-block rounded px-1.5 py-px font-mono text-[9.5px] ${
                              fc.sources?.includes(a)
                                ? "bg-threat-neutral/15 text-threat-neutral"
                                : "bg-white/[0.06] text-slate-500"
                            }`}
                          >
                            {a}{fc.sources?.includes(a) ? "" : " — no hits"}
                          </span>
                        ))}
                      </p>
                    )}
                    {(fc.matches?.length ?? 0) > 0 && (
                      <div className="mt-2 space-y-1.5">
                        {fc.matches!.map((m) => (
                          <div key={m.link} className="rounded-lg bg-white/[0.03] p-2">
                            <a
                              href={safeHref(m.link)}
                              target="_blank"
                              rel="noreferrer"
                              className="block text-[11px] text-sky-400 hover:underline"
                            >
                              {m.title}
                            </a>
                            <div className="mt-0.5 flex items-center gap-1.5 text-[9.5px] text-slate-500">
                              {m.source && <span>{m.source}</span>}
                              {m.api && (
                                <span className="rounded bg-white/[0.06] px-1 py-px font-mono">
                                  via {m.api}
                                </span>
                              )}
                            </div>
                            {m.description && (
                              <p className="mt-0.5 text-[10px] leading-relaxed text-slate-500">
                                {m.description}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </Section>
                ) : (
                  <button
                    onClick={runFactCheck}
                    disabled={checking}
                    className="glass mt-4 flex w-full items-center justify-center gap-2 border border-white/[0.12] p-3 text-xs font-semibold text-slate-300 hover:bg-white/[0.06] disabled:opacity-60"
                  >
                    <Newspaper size={14} />
                    {checking
                      ? "Searching Google News, GNews and NewsAPI…"
                      : "Check this against news sources"}
                  </button>
                )}

                {/* ── analyst dossier ───────────────────────────────────── */}
                {report ? (
                  <Section
                    title="Evidence dossier"
                    icon={ScrollText}
                    accent="#38BDF8"
                    right={
                      <span className="font-mono text-[10px] font-bold text-sky-400">
                        confidence {((report.confidence ?? 0) * 100).toFixed(0)}%
                      </span>
                    }
                  >
                    {report.summary && (
                      <p className="mt-2 text-[11.5px] leading-relaxed text-slate-300">
                        {report.summary}
                      </p>
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
                            <div
                              key={i}
                              className="rounded-lg border-l-2 border-sky-500/40 bg-white/[0.03] px-2 py-1.5"
                            >
                              <p className="text-[11px] text-slate-200">“{e.quote}”</p>
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
                                href={safeHref(m.link)}
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
                          <p className="mt-0.5 leading-relaxed text-slate-400">
                            {report.account_assessment}
                          </p>
                        </div>
                      )}
                      {report.risk_assessment && (
                        <div className="rounded-lg bg-white/[0.03] p-2">
                          <div className="text-slate-500">Risk assessment</div>
                          <p className="mt-0.5 leading-relaxed text-slate-400">
                            {report.risk_assessment}
                          </p>
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
                          <p className="mt-0.5 leading-relaxed text-slate-400">
                            {report.limitations}
                          </p>
                        </div>
                      )}
                    </div>
                    <p className="mt-2 text-right font-mono text-[9.5px] text-slate-600">
                      {report.model} · {report.generated_at?.slice(0, 19).replace("T", " ")} UTC
                    </p>
                  </Section>
                ) : (
                  <button
                    onClick={generateDossier}
                    disabled={dossierBusy}
                    className="glass mt-4 flex w-full items-center justify-center gap-2 border border-sky-500/30 p-3 text-xs font-semibold text-slate-300 hover:bg-white/[0.06] disabled:opacity-60"
                  >
                    <ScrollText size={14} />
                    {dossierBusy
                      ? "Compiling evidence dossier…"
                      : dossierError
                        ? "Failed — tap to retry evidence dossier"
                        : "Generate evidence dossier (detailed analysis)"}
                  </button>
                )}

                {/* ── actions ───────────────────────────────────────────── */}
                <div className="mt-4 flex items-center gap-2 pb-2">
                  {post.url && (
                    <a
                      href={safeHref(post.url)}
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
                        <Flag size={13} /> {busy ? "Filing…" : "Escalate"}
                      </>
                    )}
                  </button>
                </div>
                {escalated && (
                  <p className="mt-1 text-right font-mono text-[10px] text-slate-500">
                    escalation report {escalated} filed → Reports
                  </p>
                )}
              </>
            )}
          </motion.aside>
        </>
      )}
    </AnimatePresence>,
    document.body
  );
}
