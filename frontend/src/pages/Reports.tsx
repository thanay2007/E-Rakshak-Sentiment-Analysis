import { AnimatePresence, motion } from "framer-motion";
import { AlertCircle, ArrowUpRight, CheckCircle2, Download, FilePlus2, FileSpreadsheet, FileText, ShieldAlert, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useModalDialog } from "../hooks/useModalDialog";
import { readableReportText, reportPeriod } from "../lib/reportPeriod";
import { SentimentBadge } from "../components/Badges";
import { usePostDetail } from "../components/PostDetailProvider";
import GlassCard from "../components/GlassCard";
import { SkeletonRow } from "../components/Skeletons";
import { SENTIMENT_TEXT, sentimentColor } from "../data/constants";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import type { Post, Report } from "../services/api";

type Notice = { type: "success" | "error"; message: string };

function ReportNotice({ notice, onClose }: { notice: Notice; onClose: () => void }) {
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => {
    if (notice.type !== "success") return;
    const timer = window.setTimeout(() => closeRef.current(), 6000);
    return () => window.clearTimeout(timer);
  }, [notice]);
  const Icon = notice.type === "success" ? CheckCircle2 : AlertCircle;
  return createPortal(
    <div className="pointer-events-none fixed inset-x-0 top-6 z-[70] flex justify-center px-4">
      <div role={notice.type === "error" ? "alert" : "status"} className="pointer-events-auto flex w-full max-w-md items-start gap-3 rounded-xl border border-white/15 bg-base-800 p-4 text-sm text-slate-200 shadow-2xl">
        <Icon size={20} className={`mt-0.5 shrink-0 ${notice.type === "success" ? "text-threat-neutral" : "text-threat-critical"}`} aria-hidden="true" />
        <p className="min-w-0 flex-1">{notice.message}</p>
        <button onClick={onClose} aria-label="Dismiss message" className="shrink-0 rounded p-1 text-slate-400 hover:bg-white/10"><X size={16} /></button>
      </div>
    </div>, document.body
  );
}

type ReportPost = Pick<Post, "id" | "platform" | "author_handle" | "language" | "location" | "text" | "translation" | "sentiment_label" | "concern_score"> & {
  concern_level?: string;
  review_reasons?: string[];
  suggested_action?: string;
};

interface ReportPayload {
  summary?: string;
  summary_points?: string[];
  totals?: Record<string, number>;
  sentiment_distribution?: Record<string, number>;
  top_concern?: ReportPost[];
  follow_up_posts?: ReportPost[];
  concern_thresholds?: { medium: number; high: number; critical: number };
  recommended_actions?: string[];
  escalation?: {
    priority?: string;
    incident_type?: string;
    platform?: string;
    language?: string;
    location?: string;
    author?: { handle?: string };
    evidence?: { english_translation?: string; original_text?: string; sentiment?: string; concern_score?: number };
    recommended_actions?: string[];
  };
}

const TOTAL_LABELS: Record<string, string> = {
  posts: "Posts checked", negative_posts: "Negative posts", flagged_posts: "Posts needing review",
  alerts: "Alerts raised", critical_alerts: "Critical alerts", avg_concern_score: "Average concern score",
};

function ReportPosts({ posts, medium = false }: { posts: ReportPost[]; medium?: boolean }) {
  const { openPostId } = usePostDetail();
  return <div className="space-y-2">
    {posts.map(post => <article key={post.id} className={`rounded-xl border p-3 transition-colors ${medium ? "border-accent/30 bg-accent/[0.04]" : "border-white/[0.06] bg-base-950/60"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <SentimentBadge label={post.sentiment_label} />
        <div className="min-w-0 break-words font-mono text-[13px] text-slate-400">{post.platform} · <span className="break-all">@{post.author_handle}</span></div>
        <span className={`ml-auto rounded-md border px-2 py-0.5 font-mono text-xs font-bold ${medium ? "border-accent/30 bg-accent/10 text-accent" : "border-white/10 bg-white/[0.06] text-slate-200"}`}>
          {medium ? "Medium concern" : (post.concern_level ?? "Priority")} · {Math.round(post.concern_score)}/100
        </span>
      </div>
      <p className="mt-1 font-mono text-xs text-slate-400">{post.language} · {post.location || "Location not available"}</p>
      <p className="mt-2 whitespace-pre-line break-words text-xs leading-relaxed text-slate-200">{post.translation || post.text}</p>
      {post.review_reasons?.length ? <div className="mt-3 border-t border-white/[0.06] pt-2">
        <h4 className="break-words font-mono text-xs font-black uppercase tracking-widest text-accent">Why this needs follow-up</h4>
        <ul className="mt-1.5 list-disc space-y-1 pl-4 text-xs leading-relaxed text-slate-300">{post.review_reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
      </div> : null}
      {post.suggested_action && <p className="mt-2 text-xs leading-relaxed text-slate-300"><strong>Next step: </strong>{post.suggested_action}</p>}
      <button onClick={() => openPostId(post.id)} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-accent hover:underline">View full post details <ArrowUpRight size={13} /></button>
    </article>)}
  </div>;
}

function ReportModal({ report, onClose, onNotice }: { report: Report; onClose: () => void; onNotice: (notice: Notice) => void }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useModalDialog(true, onClose, dialogRef);
  const [downloading, setDownloading] = useState<"pdf" | "xlsx" | null>(null);
  const p = (report.payload ?? {}) as ReportPayload;
  const esc = p.escalation;
  const dist = p.sentiment_distribution ?? {};
  const total = Object.values(dist).reduce((sum, count) => sum + count, 0) || 1;
  const summary = p.summary_points?.length ? p.summary_points : p.summary ? p.summary.split("\n").filter(Boolean) : [];
  const urgent = p.top_concern ?? [];
  const medium = p.follow_up_posts ?? [];
  const actions = esc?.recommended_actions ?? p.recommended_actions ?? [];

  const download = async (format: "pdf" | "xlsx") => {
    if (downloading) return;
    setDownloading(format);
    try {
      if (format === "pdf") await api.downloadReport(report.id);
      else await api.downloadReportXlsx(report.id);
      onNotice({ type: "success", message: `${format === "pdf" ? "PDF" : "Excel file"} download started.` });
    } catch {
      onNotice({ type: "error", message: "Could not download the file. Please try again." });
    } finally { setDownloading(null); }
  };

  return createPortal(
    <motion.div className="fixed inset-0 z-40 flex items-center justify-center p-4 sm:p-6" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/70 backdrop-blur-md" aria-hidden="true" onClick={onClose} />
      <motion.div ref={dialogRef} tabIndex={-1} className="relative z-10 max-h-[calc(100dvh-2rem)] w-full min-w-0 max-w-2xl overflow-y-auto overscroll-contain rounded-2xl border border-white/[0.12] bg-base-900/95 p-4 shadow-2xl backdrop-blur-2xl focus:outline-none sm:max-h-[calc(100dvh-3rem)] sm:p-6" initial={{ opacity: 0, y: 16, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 16, scale: 0.98 }} role="dialog" aria-modal="true" aria-label="Report preview">
        <header className="flex items-start justify-between gap-3 border-b border-white/[0.08] pb-4">
          <div className="min-w-0">
            <p className="break-words font-mono text-xs font-black uppercase tracking-widest text-accent">SENTINEL · {report.kind === "escalation" ? "Police Action Report" : "Incident Report"}</p>
            <h2 className="mt-1 break-words text-base font-black leading-snug text-white sm:text-lg">{readableReportText(report.title, report.period_hours)}</h2>
            <p className="mt-1 font-mono text-xs leading-relaxed text-slate-400">Generated {new Date(report.created_at).toLocaleString("en-IN", { hour12: true, timeZone: "Asia/Kolkata" })} IST · Past {reportPeriod(report.period_hours)}</p>
          </div>
          <button onClick={onClose} className="shrink-0 rounded-xl border border-white/10 bg-white/[0.04] p-2 text-slate-400 transition-all hover:bg-white/[0.08] hover:text-white" aria-label="Close"><X size={18} /></button>
        </header>

        {summary.length > 0 && <section className="mt-4" aria-labelledby="report-summary-title">
          <h3 id="report-summary-title" className="text-xs font-bold uppercase tracking-wider text-slate-300">Report at a glance</h3>
          <ul className="mt-2 list-disc space-y-1.5 rounded-xl border border-white/[0.08] bg-white/[0.03] py-3 pl-7 pr-4 text-xs leading-relaxed text-slate-200">{summary.map((point, index) => <li key={index}>{readableReportText(point, report.period_hours)}</li>)}</ul>
        </section>}
        {p.totals && <dl className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-3">
          {Object.entries(p.totals).map(([key, value]) => <div key={key} className="flex flex-col rounded-xl border border-white/[0.06] bg-base-950/70 p-3 text-center">
            <dt className="order-2 mt-0.5 text-[13px] font-bold uppercase tracking-wider text-slate-400">{TOTAL_LABELS[key] ?? key.replaceAll("_", " ")}</dt>
            <dd className="order-1 font-mono text-xl font-black text-slate-100">{value.toLocaleString()}</dd>
          </div>)}
        </dl>}
        {Object.keys(dist).length > 0 && <section className="mt-4 rounded-xl border border-white/[0.06] bg-base-950/40 p-4">
          <h3 className="mb-2.5 text-xs font-bold uppercase tracking-wider text-slate-300">Post tone summary</h3>
          {Object.entries(dist).map(([label, count]) => <div key={label} className="mb-2 flex items-center gap-3 text-xs">
            <span className="w-20 shrink-0 font-semibold text-slate-300">{SENTIMENT_TEXT[label] ?? label}</span>
            <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-white/[0.06]"><div className="h-full rounded-full" style={{ width: `${count / total * 100}%`, backgroundColor: sentimentColor(label) }} /></div>
            <span className="w-12 shrink-0 text-right font-mono font-bold text-slate-200">{count}</span>
          </div>)}
        </section>}
        <section className="mt-4" aria-labelledby="report-priority-title">
          <h3 id="report-priority-title" className="text-xs font-bold uppercase tracking-wider text-slate-300">Priority posts — review first</h3>
          <p className="mb-2.5 mt-1 text-[13px] leading-relaxed text-slate-400">Posts with the highest concern levels in this period.</p>
          {urgent.length ? <ReportPosts posts={urgent} /> : <p className="text-xs text-slate-400">No priority posts selected for this period.</p>}
        </section>
        {p.follow_up_posts && <section className="mt-4" aria-labelledby="report-medium-title">
          <h3 id="report-medium-title" className="text-xs font-bold uppercase tracking-wider text-accent">Medium concerns to monitor</h3>
          <p className="mb-2.5 mt-1 text-[13px] leading-relaxed text-slate-400">{p.concern_thresholds && `Scores ${p.concern_thresholds.medium}–${p.concern_thresholds.high - 1}. `}Review these posts and watch for wider sharing or repeated messages.</p>
          {medium.length ? <ReportPosts posts={medium} medium /> : <p className="text-xs text-slate-400">No medium-concern posts selected for follow-up.</p>}
        </section>}
        {esc && <section className="mt-4 rounded-xl border border-threat-inflammatory/40 bg-threat-inflammatory/[0.06] p-4">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">Police action details {esc.priority && `· ${esc.priority}`}</h3>
          <p className="mt-2.5 text-xs leading-relaxed text-slate-300">{esc.incident_type} · {esc.platform} · {esc.location || "Location not available"}</p>
          {esc.author?.handle && <p className="mt-2 break-all font-mono text-xs text-slate-300">Account: @{esc.author.handle}</p>}
          <p className="mt-2 whitespace-pre-line text-xs leading-relaxed text-slate-200">{esc.evidence?.english_translation || esc.evidence?.original_text}</p>
        </section>}
        {actions.length > 0 && <section className="mt-4">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">Suggested next steps</h3>
          <ol className="mt-2 list-disc space-y-1.5 rounded-xl border border-white/[0.06] bg-base-950/40 p-4 pl-8 text-xs leading-relaxed text-slate-300">{actions.map((action, index) => <li key={index}>{action}</li>)}</ol>
        </section>}
        {(report.has_pdf || report.has_xlsx) && <footer className="mt-5 flex flex-wrap gap-2 border-t border-white/[0.08] pt-4">
          {report.has_pdf && <button onClick={() => void download("pdf")} disabled={downloading !== null} className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-xs font-black text-base-950 shadow-md shadow-accent/20 transition-all hover:bg-accent-glow disabled:opacity-50"><Download size={16} />{downloading === "pdf" ? "Downloading PDF…" : "Download PDF"}</button>}
          {report.has_xlsx && <button onClick={() => void download("xlsx")} disabled={downloading !== null} className="inline-flex items-center gap-2 rounded-xl border border-accent/40 bg-accent/10 px-4 py-2.5 text-xs font-black text-accent transition-all hover:bg-accent/20 disabled:opacity-50"><FileSpreadsheet size={16} />{downloading === "xlsx" ? "Downloading Excel…" : "Download Excel"}</button>}
        </footer>}
      </motion.div>
    </motion.div>, document.body
  );
}

export default function Reports() {
  const { data, loading, refresh } = usePolling(() => api.reports(), 30000);
  const [open, setOpen] = useState<Report | null>(null);
  const [title, setTitle] = useState("");
  const [period, setPeriod] = useState(24);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const revealRef = useGsapReveal<HTMLDivElement>(data?.length ?? 0);

  const generate = async () => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    try {
      await api.generateReport({ title: title || undefined, period_hours: period });
      setTitle("");
      void refresh();
      setNotice({ type: "success", message: "Report generated." });
    } catch {
      setNotice({ type: "error", message: "Could not create the report. Please try again." });
    } finally {
      setBusy(false);
    }
  };

  const openFull = async (report: Report) => {
    try {
      setOpen(await api.report(report.id));
    } catch {
      setNotice({ type: "error", message: "Could not open the report. Please try again." });
    }
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
              Evidence & Incident Reports
            </h1>
            <p className="text-xs text-slate-400">
              Create incident summaries and review evidence reports
            </p>
          </div>
        </div>
      </div>

      {/* Generator Control Card */}
      <GlassCard className="flex flex-wrap items-center gap-3 p-4 border border-white/[0.08]">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Report title (e.g. Surat Incident Report)"
          className="min-w-0 w-full flex-1 sm:min-w-[260px] rounded-xl border border-white/[0.1] bg-white/[0.04] px-3.5 py-2 text-xs text-slate-100 placeholder:text-slate-500 focus:border-accent/60 focus:bg-white/[0.07] focus:outline-none"
        />
        <select
          value={period}
          onChange={(e) => setPeriod(Number(e.target.value))}
          className="rounded-xl border border-white/[0.1] bg-base-800 py-2 pl-3 pr-8 text-xs text-slate-200 hover:border-white/20 focus:border-accent/60 focus:outline-none"
        >
          <option value={6}>Past {reportPeriod(6)}</option>
          <option value={24}>Past {reportPeriod(24)}</option>
          <option value={72}>Past {reportPeriod(72)}</option>
          <option value={168}>Past {reportPeriod(168)}</option>
        </select>
        <button
          onClick={generate}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-xs font-black text-base-950 shadow-md shadow-accent/20 hover:bg-accent-light disabled:opacity-50 transition-all"
        >
          <FilePlus2 size={14} /> {busy ? "Creating Report…" : "Generate Incident Report"}
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
                          className={`rounded-md border px-2 py-0.2 font-mono text-[13px] font-black uppercase tracking-wider ${
                            escalation
                              ? "border-threat-inflammatory/50 bg-threat-inflammatory/15 text-threat-inflammatory"
                              : "border-accent/50 bg-accent/15 text-accent"
                          }`}
                        >
                          {escalation ? "Police action" : r.kind}
                        </span>
                      </div>
                      <h3 className="mt-2 line-clamp-2 text-xs font-bold text-slate-100 transition-colors group-hover:text-accent">
                        {readableReportText(r.title, r.period_hours)}
                      </h3>
                    </div>
                  </div>
                </div>

                <div className="mt-4 flex items-center justify-between border-t border-white/[0.06] pt-3">
                  <span className="font-mono text-[13px] text-slate-400">
                    {new Date(r.created_at).toLocaleString("en-IN", { hour12: true })}
                    {r.period_hours > 0 && ` · Past ${reportPeriod(r.period_hours)}`}
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

      {notice && <ReportNotice notice={notice} onClose={() => setNotice(null)} />}
      <AnimatePresence>{open && <ReportModal report={open} onClose={() => setOpen(null)} onNotice={setNotice} />}</AnimatePresence>
    </div>
  );
}
