import { AlertOctagon, BellRing, Check, CheckCheck, ChevronDown, Flag, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { SentimentBadge, SeverityChip } from "../components/Badges";
import { usePostDetail } from "../components/PostDetailProvider";
import GlassCard from "../components/GlassCard";
import { SkeletonRow } from "../components/Skeletons";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { useLiveAlerts } from "../hooks/useLive";
import { usePolling } from "../hooks/usePolling";
import { useUrlFilters } from "../hooks/useUrlFilters";
import { api } from "../services/api";
import type { Alert } from "../services/api";

const STATUS_META: Record<string, { label: string; cls: string }> = {
  new: { label: "NEW INCIDENT", cls: "text-threat-critical border-threat-critical/50 bg-threat-critical/10" },
  acknowledged: { label: "ACKNOWLEDGED", cls: "text-accent border-accent/50 bg-accent/10" },
  escalated: { label: "LE ESCALATED", cls: "text-threat-inflammatory border-threat-inflammatory/50 bg-threat-inflammatory/10" },
};

function AlertRow({ alert, onAction, onOpenPost }: {
  alert: Alert;
  onAction: (id: string, action: "acknowledge" | "escalate") => void;
  onOpenPost: (postId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const esc = alert.escalation as any;

  return (
    <GlassCard
      hover
      className={`reveal-item transition-all duration-200 p-4 rounded-2xl border ${
        alert.severity === "critical" && alert.status === "new"
          ? "border-threat-critical/50 bg-threat-critical/[0.04] shadow-[0_0_24px_-8px_rgba(220,38,38,0.35)]"
          : "border-white/[0.08]"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0 flex-1">
          <SeverityChip severity={alert.severity} />
          <span className={`rounded-md border px-2 py-0.5 font-mono text-[9.5px] font-extrabold tracking-wider ${STATUS_META[alert.status].cls}`}>
            {STATUS_META[alert.status].label}
          </span>
          <span className="truncate text-sm font-bold text-slate-100">{alert.title}</span>
        </div>

        <div className="flex items-center gap-3 shrink-0 font-mono text-xs">
          <span className="text-slate-400">
            {new Date(alert.created_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}
          </span>
          <span className="inline-flex items-center gap-1 rounded-md bg-white/[0.06] px-2 py-0.5 font-bold text-slate-200">
            Threat {Math.round(alert.concern_score)}
          </span>
          <button
            onClick={() => setOpen((o) => !o)}
            className="rounded-lg border border-white/10 bg-white/[0.04] p-1.5 text-slate-400 hover:bg-white/[0.08] hover:text-white transition-all"
            aria-label="Expand alert details"
          >
            <ChevronDown size={14} className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
          </button>
        </div>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-slate-300">{alert.summary}</p>

      {open && (
        <div className="mt-3.5 space-y-3 rounded-xl border border-white/[0.08] bg-base-950/80 p-3.5 backdrop-blur-md">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.06] pb-2.5 text-xs text-slate-300">
            <div className="flex items-center gap-2">
              <SentimentBadge label={alert.category} score={alert.concern_score} />
              <span className="font-semibold text-slate-200">{alert.platform}</span>
              {alert.location && <span className="text-slate-400">· {alert.location}</span>}
            </div>
            <button
              onClick={() => onOpenPost(alert.post_id)}
              className="font-semibold text-accent hover:underline inline-flex items-center gap-1 text-xs"
            >
              Inspect Source Post →
            </button>
          </div>

          {esc?.recommended_actions && (
            <div>
              <div className="mb-1.5 flex items-center gap-1 text-[10.5px] font-bold uppercase tracking-widest text-slate-400">
                <AlertOctagon size={12} className="text-threat-inflammatory" />
                <span>Auto-Generated Escalation Packet ({esc.priority})</span>
              </div>
              <ul className="space-y-1 text-xs text-slate-200">
                {(esc.recommended_actions as string[]).map((a, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-threat-inflammatory font-bold">▸</span>
                    <span>{a}</span>
                  </li>
                ))}
              </ul>
              {esc.note && <p className="mt-2 text-xs italic text-slate-400">{esc.note}</p>}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-white/[0.06]">
            {alert.status === "new" && (
              <button
                onClick={() => onAction(alert.id, "acknowledge")}
                className="inline-flex items-center gap-1.5 rounded-xl border border-accent/40 bg-accent/15 px-3 py-1.5 text-xs font-bold text-accent shadow-sm hover:bg-accent/25 transition-all"
              >
                <Check size={13} /> Acknowledge Alert
              </button>
            )}
            {alert.status !== "escalated" && (
              <button
                onClick={() => onAction(alert.id, "escalate")}
                className="inline-flex items-center gap-1.5 rounded-xl bg-threat-critical px-3.5 py-1.5 text-xs font-bold text-white shadow-md hover:bg-red-600 transition-all"
              >
                <Flag size={13} /> Escalate to Police Cyber Cell
              </button>
            )}
            {alert.status === "escalated" && (
              <span className="inline-flex items-center gap-1.5 font-mono text-xs font-bold text-threat-inflammatory">
                <CheckCheck size={14} /> Escalation report dispatched to law enforcement unit
              </span>
            )}
          </div>
        </div>
      )}
    </GlassCard>
  );
}

export default function Alerts() {
  // In the URL, not in state: the assistant filters this page by navigating to
  // it with `?severity=critical`, and a filtered view stays linkable.
  const { get, set, clear } = useUrlFilters();
  const statusFilter = get("status");
  const severityFilter = get("severity");
  const { data, loading, refresh } = usePolling(
    () => api.alerts({ status: statusFilter || undefined, severity: severityFilter || undefined, limit: 60 }),
    20000,
    [statusFilter, severityFilter]
  );
  useLiveAlerts(); // keeps the shared socket hot
  const { openPostId } = usePostDetail();
  const revealRef = useGsapReveal<HTMLDivElement>(`${statusFilter}-${severityFilter}-${data?.length ?? 0}`);

  const counts = useMemo(() => {
    const c = { critical: 0, high: 0, medium: 0, new: 0, total: data?.length ?? 0 };
    for (const a of data ?? []) {
      if (a.severity in c) (c as any)[a.severity]++;
      if (a.status === "new") c.new++;
    }
    return c;
  }, [data]);

  const act = async (id: string, action: "acknowledge" | "escalate") => {
    try {
      if (action === "acknowledge") await api.acknowledgeAlert(id);
      else await api.escalateAlert(id);
      refresh();
    } catch { /* polling will resync */ }
  };

  return (
    <div className="space-y-4">
      {/* Executive Command Bar */}
      <div className="flex flex-col gap-3 rounded-2xl border border-white/[0.08] bg-base-950/80 p-4 shadow-xl backdrop-blur-xl md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-threat-critical/40 bg-threat-critical/15 text-threat-critical shadow-[0_0_15px_rgba(239,68,68,0.25)]">
            <BellRing size={20} />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-white sm:text-base">
              Threat Alerts & Critical Incidents
            </h1>
          </div>
        </div>

        {/* Severity Count Badges */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-xl border border-threat-critical/40 bg-threat-critical/15 px-2.5 py-1 text-xs font-bold text-threat-critical">
            <span className="h-2 w-2 rounded-full bg-threat-critical animate-pulse" />
            <span>{counts.critical} Critical</span>
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-xl border border-threat-inflammatory/40 bg-threat-inflammatory/15 px-2.5 py-1 text-xs font-bold text-threat-inflammatory">
            <span>{counts.high} High</span>
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-xl border border-accent/40 bg-accent/15 px-2.5 py-1 text-xs font-bold text-accent">
            <span>{counts.new} Unhandled</span>
          </span>
        </div>
      </div>

      {/* Filter Row */}
      <GlassCard className="flex flex-wrap items-center justify-between gap-3 p-3.5 border border-white/[0.08]">
        <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-300">
          <ShieldAlert size={15} className="text-accent" /> Filter Queue:
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select
            value={severityFilter}
            onChange={(e) => set("severity", e.target.value)}
            className="rounded-xl border border-white/[0.1] bg-base-800 py-1.5 pl-3 pr-8 text-xs text-slate-200 hover:border-white/20 focus:border-accent/60 focus:outline-none"
          >
            <option value="">All Severities</option>
            <option value="critical">Critical Severity</option>
            <option value="high">High Severity</option>
            <option value="medium">Medium Severity</option>
          </select>

          <select
            value={statusFilter}
            onChange={(e) => set("status", e.target.value)}
            className="rounded-xl border border-white/[0.1] bg-base-800 py-1.5 pl-3 pr-8 text-xs text-slate-200 hover:border-white/20 focus:border-accent/60 focus:outline-none"
          >
            <option value="">All Triage Statuses</option>
            <option value="new">New Incident</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="escalated">Escalated to LE</option>
          </select>

          {(severityFilter || statusFilter) && (
            <button
              onClick={() => clear("severity", "status")}
              className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-white/[0.08]"
            >
              Clear Filters
            </button>
          )}
        </div>
      </GlassCard>

      {/* Incident List */}
      {loading && !data ? (
        <SkeletonRow n={7} />
      ) : (
        <div ref={revealRef} className="space-y-3">
          {data?.map((a) => (
            <AlertRow key={a.id} alert={a} onAction={act} onOpenPost={openPostId} />
          ))}
          {data?.length === 0 && (
            <GlassCard className="p-12 text-center text-xs text-slate-400">
              No active alerts matching the selected triage filter.
            </GlassCard>
          )}
        </div>
      )}

    </div>
  );
}

