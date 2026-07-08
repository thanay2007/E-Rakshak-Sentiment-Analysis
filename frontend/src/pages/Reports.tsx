import { AnimatePresence, motion } from "framer-motion";
import { Download, FilePlus2, FileText, X } from "lucide-react";
import { useState } from "react";
import { ThreatBadge } from "../components/Badges";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import { SkeletonRow } from "../components/Skeletons";
import { THREAT_COLORS, THREAT_SHORT } from "../data/constants";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import type { Report } from "../services/api";

function ReportModal({ report, onClose }: { report: Report; onClose: () => void }) {
  const p = report.payload ?? {};
  const esc = p.escalation;
  const dist: Record<string, number> = p.category_distribution ?? {};
  const total = Object.values(dist).reduce((s, v) => s + v, 0) || 1;

  return (
    <>
      <motion.div
        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onClick={onClose}
      />
      <motion.div
        className="fixed inset-x-4 top-[6vh] z-50 mx-auto max-h-[86vh] max-w-2xl overflow-y-auto rounded-2xl border border-white/10 bg-base-800/97 p-6 backdrop-blur-2xl"
        initial={{ opacity: 0, y: 26, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 26, scale: 0.97 }}
        transition={{ type: "spring", damping: 26, stiffness: 280 }}
        role="dialog" aria-label="Report preview"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-accent">
              SENTINEL · {report.kind} report · {report.id}
            </div>
            <h2 className="mt-1 text-lg font-bold text-slate-100">{report.title}</h2>
            <div className="font-mono text-[11px] text-slate-500">
              generated {new Date(report.created_at).toLocaleString("en-IN")}
            </div>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10" aria-label="Close">
            <X size={16} />
          </button>
        </div>

        {p.summary && (
          <p className="mt-4 rounded-xl border border-white/[0.06] bg-white/[0.03] p-4 text-[13px] leading-relaxed text-slate-300">
            {p.summary}
          </p>
        )}

        {p.totals && (
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
            {Object.entries(p.totals as Record<string, number>).map(([k, v]) => (
              <div key={k} className="rounded-xl bg-white/[0.04] p-2.5 text-center">
                <div className="font-mono text-lg font-bold text-slate-200">{v}</div>
                <div className="text-[9px] uppercase tracking-wider text-slate-500">{k.replace(/_/g, " ")}</div>
              </div>
            ))}
          </div>
        )}

        {Object.keys(dist).length > 0 && (
          <div className="mt-4">
            <h3 className="mb-2 text-[11px] font-bold uppercase tracking-widest text-slate-500">Classification breakdown</h3>
            {Object.entries(dist).map(([label, count]) => (
              <div key={label} className="mb-1.5 flex items-center gap-2 text-[11.5px]">
                <span className="w-28 text-slate-400">{THREAT_SHORT[label] ?? label}</span>
                <div className="h-1.5 flex-1 rounded-full bg-white/[0.06]">
                  <div className="h-full rounded-full" style={{ width: `${(count / total) * 100}%`, backgroundColor: THREAT_COLORS[label] ?? "#64748B" }} />
                </div>
                <span className="w-10 text-right font-mono text-slate-400">{count}</span>
              </div>
            ))}
          </div>
        )}

        {p.top_threats?.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-2 text-[11px] font-bold uppercase tracking-widest text-slate-500">Top threats</h3>
            <div className="space-y-2">
              {p.top_threats.slice(0, 5).map((t: any) => (
                <div key={t.id} className="rounded-xl bg-white/[0.03] p-2.5">
                  <div className="flex items-center gap-2">
                    <ThreatBadge label={t.threat_label} score={t.threat_score} />
                    <span className="font-mono text-[10px] text-slate-500">
                      {t.platform} @{t.author_handle} · {t.language} · {t.location || "n/a"}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[12px] text-slate-300">{t.translation || t.text}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {p.coordinated_clusters?.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-2 text-[11px] font-bold uppercase tracking-widest text-slate-500">Coordinated amplification</h3>
            {p.coordinated_clusters.slice(0, 3).map((c: any) => (
              <p key={c.id} className="mb-1.5 text-[11.5px] text-slate-400">
                <span className="font-mono font-bold text-threat-critical">{c.id}</span>{" "}
                {c.label} · {(c.confidence * 100).toFixed(0)}% confidence · {c.why?.join("; ")}
              </p>
            ))}
          </div>
        )}

        {esc && (
          <div className="mt-4 rounded-xl border border-threat-inflammatory/30 bg-threat-inflammatory/[0.05] p-4">
            <h3 className="text-[11px] font-bold uppercase tracking-widest text-threat-inflammatory">
              Escalation packet · {esc.priority}
            </h3>
            <div className="mt-2 space-y-1 text-[12px] text-slate-300">
              <p><span className="text-slate-500">Incident:</span> {esc.incident_type} on {esc.platform} ({esc.language}, {esc.location || "n/a"})</p>
              <p><span className="text-slate-500">Author:</span> @{esc.author?.handle} · {esc.author?.followers} followers · {esc.author?.account_age_days}d old</p>
              <p><span className="text-slate-500">Evidence:</span> {esc.evidence?.english_translation || esc.evidence?.original_text}</p>
              <p><span className="text-slate-500">Classification:</span> {esc.evidence?.classification} · score {esc.evidence?.threat_score}</p>
            </div>
            {esc.recommended_actions && (
              <ul className="mt-2 space-y-1 text-[11.5px] text-slate-300">
                {esc.recommended_actions.map((a: string, i: number) => (
                  <li key={i} className="flex gap-1.5"><span className="text-threat-inflammatory">▸</span> {a}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {p.recommended_actions?.length > 0 && !esc && (
          <div className="mt-4">
            <h3 className="mb-2 text-[11px] font-bold uppercase tracking-widest text-slate-500">Recommended actions</h3>
            <ul className="space-y-1 text-[12px] text-slate-300">
              {p.recommended_actions.map((a: string, i: number) => (
                <li key={i} className="flex gap-1.5"><span className="text-accent">▸</span> {a}</li>
              ))}
            </ul>
          </div>
        )}

        {report.has_pdf && (
          <a
            href={api.reportDownloadUrl(report.id)}
            className="glow-accent mt-5 inline-flex items-center gap-2 rounded-xl border border-accent/50 bg-accent/15 px-4 py-2 text-xs font-bold text-accent hover:bg-accent hover:text-base-900"
          >
            <Download size={14} /> Download PDF
          </a>
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
      <div>
        <h1 className="flex items-center gap-2 text-lg font-bold text-slate-200">
          <FileText size={18} className="text-accent" /> Analytics & Reports
        </h1>
        <p className="text-xs text-slate-500">generated incident reports · escalation packets · PDF export</p>
      </div>

      <GlassCard className="flex flex-wrap items-center gap-3 p-4">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Report title (optional)"
          className="w-64 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:border-accent/40 focus:outline-none"
        />
        <select value={period} onChange={(e) => setPeriod(Number(e.target.value))} className="rounded-xl border border-white/[0.08] bg-base-800 px-2.5 py-2 text-xs text-slate-400">
          <option value={6}>Last 6 hours</option>
          <option value={24}>Last 24 hours</option>
          <option value={72}>Last 72 hours</option>
          <option value={168}>Last 7 days</option>
        </select>
        <button
          onClick={generate}
          disabled={busy}
          className="glow-accent inline-flex items-center gap-2 rounded-xl border border-accent/50 bg-accent/15 px-4 py-2 text-xs font-bold text-accent transition-all hover:bg-accent hover:text-base-900 disabled:opacity-50"
        >
          <FilePlus2 size={14} /> {busy ? "Generating…" : "Generate Incident Report"}
        </button>
      </GlassCard>

      {loading && !data ? (
        <SkeletonRow n={5} />
      ) : (
        <div ref={revealRef} className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data?.map((r) => (
            <GlassCard key={r.id} hover className="reveal-item cursor-pointer p-4" onClick={() => openFull(r)}>
              <div className="flex items-center gap-2">
                <span className={`rounded-md border px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider ${
                  r.kind === "escalation"
                    ? "border-threat-inflammatory/50 bg-threat-inflammatory/10 text-threat-inflammatory"
                    : "border-accent/50 bg-accent/10 text-accent"
                }`}>
                  {r.kind}
                </span>
                {r.has_pdf && <Download size={12} className="text-slate-600" />}
                <span className="ml-auto font-mono text-[10px] text-slate-600">{r.id}</span>
              </div>
              <h3 className="mt-2 line-clamp-2 text-[13px] font-semibold text-slate-200">{r.title}</h3>
              <div className="mt-1.5 font-mono text-[10.5px] text-slate-500">
                {new Date(r.created_at).toLocaleString("en-IN")}
                {r.period_hours > 0 && ` · ${r.period_hours}h window`}
              </div>
            </GlassCard>
          ))}
          {data?.length === 0 && (
            <GlassCard className="col-span-full p-10 text-center text-sm text-slate-500">
              No reports yet — generate one above.
            </GlassCard>
          )}
        </div>
      )}

      <AnimatePresence>{open && <ReportModal report={open} onClose={() => setOpen(null)} />}</AnimatePresence>
    </div>
  );
}
