import { AnimatePresence, motion } from "framer-motion";
import { ArrowUpRight, Download, FilePlus2, FileText, ShieldAlert, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { SentimentBadge } from "../components/Badges";
import { usePostDetail } from "../components/PostDetailProvider";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import { SkeletonRow } from "../components/Skeletons";
import { SENTIMENT_TEXT, sentimentColor } from "../data/constants";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import type { Report } from "../services/api";

function ReportModal({ report, onClose }: { report: Report; onClose: () => void }) {
  const { openPostId } = usePostDetail();
  const p = report.payload ?? {};
  const esc = p.escalation;
  const dist: Record<string, number> = p.sentiment_distribution ?? {};
  const total = Object.values(dist).reduce((s, v) => s + v, 0) || 1;

  return (
    <>
      <motion.div
        className="fixed inset-0 z-40 bg-black/70 backdrop-blur-md"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      />
      <motion.div
        className="fixed inset-x-4 top-[5vh] z-50 mx-auto max-h-[90vh] max-w-2xl overflow-y-auto rounded-2xl border border-white/[0.12] bg-base-900/95 p-6 shadow-2xl backdrop-blur-2xl"
        initial={{ opacity: 0, y: 26, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 26, scale: 0.97 }}
        transition={{ type: "spring", damping: 26, stiffness: 280 }}
        role="dialog"
        aria-label="Report preview"
      >
        <div className="flex items-start justify-between gap-3 border-b border-white/[0.08] pb-4">
          <div>
            <div className="font-mono text-[10px] font-black uppercase tracking-widest text-accent">
              E-RAKSHAK INTELLIGENCE · {report.kind.toUpperCase()} REPORT · {report.id}
            </div>
            <h2 className="mt-1 text-base font-black text-white sm:text-lg">{report.title}</h2>
            <div className="font-mono text-xs text-slate-400">
              Generated: {new Date(report.created_at).toLocaleString("en-IN")}
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-xl border border-white/10 bg-white/[0.04] p-2 text-slate-400 hover:bg-white/[0.08] hover:text-white transition-all"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        {p.summary && (
          <p className="mt-4 rounded-xl border border-white/[0.08] bg-white/[0.03] p-4 text-xs leading-relaxed text-slate-200">
            {p.summary}
          </p>
        )}

        {p.totals && (
          <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-5">
            {Object.entries(p.totals as Record<string, number>).map(([k, v]) => (
              <div key={k} className="rounded-xl border border-white/[0.06] bg-base-950/70 p-3 text-center">
                <div className="font-mono text-xl font-black text-slate-100">{v}</div>
                <div className="mt-0.5 text-[9.5px] font-bold uppercase tracking-wider text-slate-400">
                  {k.replace(/_/g, " ")}
                </div>
              </div>
            ))}
          </div>
        )}

        {Object.keys(dist).length > 0 && (
          <div className="mt-4 rounded-xl border border-white/[0.06] bg-base-950/40 p-4">
            <h3 className="mb-2.5 text-xs font-bold uppercase tracking-wider text-slate-300">
              Threat Category Breakdown
            </h3>
            {Object.entries(dist).map(([label, count]) => (
              <div key={label} className="mb-2 flex items-center gap-3 text-xs">
                <span className="w-32 truncate text-slate-300 font-semibold">{SENTIMENT_TEXT[label] ?? label}</span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/[0.08]">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${(count / total) * 100}%`,
                      backgroundColor: sentimentColor(label),
                    }}
                  />
                </div>
                <span className="w-12 text-right font-mono font-bold text-slate-200">{count}</span>
              </div>
            ))}
          </div>
        )}

        {p.top_concern?.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-2.5 text-xs font-bold uppercase tracking-wider text-slate-300">
              Highest-Concern Posts
            </h3>
            <div className="space-y-2">
              {p.top_concern.slice(0, 5).map((t: any) => (
                <button
                  key={t.id}
                  onClick={() => openPostId(t.id)}
                  className="w-full rounded-xl border border-white/[0.06] bg-base-950/60 p-3 text-left transition-colors hover:border-accent/40 hover:bg-white/[0.04]"
                >
                  <div className="flex items-center gap-2">
                    <SentimentBadge label={t.sentiment_label} score={t.concern_score} />
                    <span className="font-mono text-[11px] text-slate-400">
                      {t.platform} @{t.author_handle} · {t.language} · {t.location || "Gujarat"}
                    </span>
                  </div>
                  <p className="mt-1.5 line-clamp-2 text-xs text-slate-200">{t.translation || t.text}</p>
                  <span className="mt-1 block text-[10.5px] font-semibold text-accent">
                    open full detail →
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {esc && (
          <div className="mt-4 rounded-xl border border-threat-inflammatory/40 bg-threat-inflammatory/[0.06] p-4">
            <h3 className="text-xs font-black uppercase tracking-wider text-threat-inflammatory">
              Tactical Escalation Dossier · {esc.priority.toUpperCase()}
            </h3>
            <div className="mt-2.5 space-y-1.5 text-xs text-slate-200">
              <p><strong className="text-slate-400">Incident:</strong> {esc.incident_type} on {esc.platform} ({esc.language}, {esc.location || "Gujarat"})</p>
              <p><strong className="text-slate-400">Target Profile:</strong> @{esc.author?.handle} · {esc.author?.followers} followers · {esc.author?.account_age_days}d account age</p>
              <p><strong className="text-slate-400">Evidence Quote:</strong> {esc.evidence?.english_translation || esc.evidence?.original_text}</p>
              <p><strong className="text-slate-400">Classification:</strong> {esc.evidence?.classification} (Score {esc.evidence?.concern_score}/100)</p>
            </div>
            {esc.recommended_actions && (
              <ul className="mt-3 space-y-1.5 text-xs text-slate-300">
                {esc.recommended_actions.map((a: string, i: number) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <span className="text-threat-inflammatory font-bold">▸</span>
                    <span>{a}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {p.recommended_actions?.length > 0 && !esc && (
          <div className="mt-4 rounded-xl border border-white/[0.06] bg-base-950/40 p-4">
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-300">
              Recommended Law Enforcement Actions
            </h3>
            <ul className="space-y-1.5 text-xs text-slate-300">
              {p.recommended_actions.map((a: string, i: number) => (
                <li key={i} className="flex items-start gap-1.5">
                  <span className="text-accent font-bold">▸</span>
                  <span>{a}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {report.has_pdf && (
          <div className="mt-5 border-t border-white/[0.08] pt-4">
            <button
              onClick={() => void api.downloadReport(report.id)}
              className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-xs font-black text-base-950 shadow-md shadow-accent/20 hover:bg-accent-light transition-all"
            >
              <Download size={14} /> Download Official PDF Dossier
            </button>
          </div>
        )}
      </motion.div>
    </>
  );
}

export default function Reports() {
  const { data, loading, refresh } = usePolling(() => api.reports(), 30000);
  const [open, setOpen] = useState<Report | null>(null);
  const [title, setTitle] = useState("");
  const [period, setPeriod] = useState(24);
  const [busy, setBusy] = useState(false);
  const revealRef = useGsapReveal<HTMLDivElement>(data?.length ?? 0);

  const generate = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await api.generateReport({ title: title || undefined, period_hours: period });
      setTitle("");
      refresh();
      setOpen(r);
    } finally {
      setBusy(false);
    }
  };

  const openFull = async (r: Report) => {
    setOpen(await api.report(r.id));
  };

  return (
    <div className="space-y-4">
      {/* Executive Command Header */}
      <div className="flex flex-col gap-3 rounded-2xl border border-white/[0.08] bg-base-950/80 p-4 shadow-xl backdrop-blur-xl md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-accent/40 bg-accent/15 text-accent shadow-[0_0_15px_rgba(20,184,196,0.25)]">
            <FileText size={20} />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-white sm:text-base">
              Intelligence Dossiers & Incident Reports
            </h1>
            <p className="text-xs text-slate-400">
              Automated briefing generator · Formal PDF escalation packets · Evidence timeline exports
            </p>
          </div>
        </div>
      </div>

      {/* Generator Control Card */}
      <GlassCard className="flex flex-wrap items-center gap-3 p-4 border border-white/[0.08]">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Custom dossier title (e.g. Surat Riot Escalation)"
          className="min-w-[260px] flex-1 rounded-xl border border-white/[0.1] bg-white/[0.04] px-3.5 py-2 text-xs text-slate-100 placeholder:text-slate-500 focus:border-accent/60 focus:bg-white/[0.07] focus:outline-none"
        />
        <select
          value={period}
          onChange={(e) => setPeriod(Number(e.target.value))}
          className="rounded-xl border border-white/[0.1] bg-base-800 py-2 pl-3 pr-8 text-xs text-slate-200 hover:border-white/20 focus:border-accent/60 focus:outline-none"
        >
          <option value={6}>Window: Last 6 Hours</option>
          <option value={24}>Window: Last 24 Hours</option>
          <option value={72}>Window: Last 72 Hours</option>
          <option value={168}>Window: Last 7 Days</option>
        </select>
        <button
          onClick={generate}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-xs font-black text-base-950 shadow-md shadow-accent/20 hover:bg-accent-light disabled:opacity-50 transition-all"
        >
          <FilePlus2 size={14} /> {busy ? "Synthesizing Dossier…" : "Generate Incident Report"}
        </button>
      </GlassCard>

      {/* Reports Grid */}
      {loading && !data ? (
        <SkeletonRow n={5} />
      ) : (
        <div ref={revealRef} className="grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3">
          {data?.map((r) => {
            const escalation = r.kind === "escalation";
            return (
              <GlassCard
                key={r.id}
                hover
                className="reveal-item group flex flex-col justify-between p-4 border border-white/[0.08] cursor-pointer"
                onClick={() => openFull(r)}
              >
                <div>
                  <div className="flex items-start gap-3">
                    <span
                      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${
                        escalation
                          ? "border-threat-inflammatory/40 bg-threat-inflammatory/15 text-threat-inflammatory"
                          : "border-accent/40 bg-accent/15 text-accent"
                      }`}
                    >
                      {escalation ? <ShieldAlert size={18} /> : <FileText size={18} />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={`rounded-md border px-2 py-0.2 font-mono text-[9.5px] font-black uppercase tracking-wider ${
                            escalation
                              ? "border-threat-inflammatory/50 bg-threat-inflammatory/15 text-threat-inflammatory"
                              : "border-accent/50 bg-accent/15 text-accent"
                          }`}
                        >
                          {r.kind}
                        </span>
                        {r.has_pdf && (
                          <span className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-1.5 py-0.2 font-mono text-[9.5px] font-bold uppercase tracking-wider text-slate-400">
                            <Download size={9} /> PDF Ready
                          </span>
                        )}
                      </div>
                      <h3 className="mt-2 line-clamp-2 text-xs font-bold text-slate-100 transition-colors group-hover:text-accent">
                        {r.title}
                      </h3>
                    </div>
                  </div>
                </div>

                <div className="mt-4 flex items-center justify-between border-t border-white/[0.06] pt-3">
                  <span className="font-mono text-[11px] text-slate-400">
                    {new Date(r.created_at).toLocaleString("en-IN")}
                    {r.period_hours > 0 && ` · ${r.period_hours}h`}
                  </span>
                  <span className="inline-flex items-center gap-1 font-mono text-xs font-bold text-slate-400 group-hover:text-accent transition-colors">
                    Review <ArrowUpRight size={13} className="transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                  </span>
                </div>
              </GlassCard>
            );
          })}
          {data?.length === 0 && (
            <GlassCard className="col-span-full flex flex-col items-center gap-3 p-12 text-center border border-white/[0.08]">
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04] text-slate-500">
                <FileText size={22} />
              </span>
              <p className="text-xs text-slate-400">No reports generated yet. Click "Generate Incident Report" above.</p>
            </GlassCard>
          )}
        </div>
      )}

      <AnimatePresence>{open && <ReportModal report={open} onClose={() => setOpen(null)} />}</AnimatePresence>
    </div>
  );
}
