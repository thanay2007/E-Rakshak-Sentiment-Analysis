import { BellRing, Check, CheckCheck, ChevronDown, Flag } from "lucide-react";
import { useMemo, useState } from "react";
import { SeverityChip, ThreatBadge } from "../components/Badges";
import DetailDrawer from "../components/DetailDrawer";
import GlassCard from "../components/GlassCard";
import { SkeletonRow } from "../components/Skeletons";
import { useGsapReveal } from "../hooks/useGsapReveal";
import { useLiveAlerts } from "../hooks/useLive";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import type { Alert, Post } from "../services/api";

const STATUS_META: Record<string, { label: string; cls: string }> = {
  new: { label: "NEW", cls: "text-threat-critical border-threat-critical/50 bg-threat-critical/10" },
  acknowledged: { label: "ACK", cls: "text-accent border-accent/50 bg-accent/10" },
  escalated: { label: "ESCALATED", cls: "text-threat-inflammatory border-threat-inflammatory/50 bg-threat-inflammatory/10" },
};

function AlertRow({ alert, onAction, onOpenPost }: {
  alert: Alert;
  onAction: (id: string, action: "acknowledge" | "escalate") => void;
  onOpenPost: (postId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const esc = alert.escalation as any;

  return (
    <GlassCard hover className={`reveal-item p-3.5 ${alert.severity === "critical" && alert.status === "new" ? "border-threat-critical/40 glow-critical" : ""}`}>
      <div className="flex items-center gap-3">
        <SeverityChip severity={alert.severity} />
        <span className={`rounded-md border px-1.5 py-0.5 font-mono text-[9px] font-bold tracking-wider ${STATUS_META[alert.status].cls}`}>
          {STATUS_META[alert.status].label}
        </span>
        <span className="truncate text-[13px] font-semibold text-slate-200">{alert.title}</span>
        <span className="ml-auto hidden font-mono text-[10px] text-slate-600 sm:block">
          {new Date(alert.created_at).toLocaleTimeString("en-IN", { hour12: false })}
        </span>
        <span className="font-mono text-xs font-bold text-slate-300">{Math.round(alert.threat_score)}</span>
        <button onClick={() => setOpen((o) => !o)} className="rounded-lg p-1 text-slate-500 hover:bg-white/10" aria-label="Expand">
          <ChevronDown size={14} className={`transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
      </div>
      <p className="mt-1.5 line-clamp-2 pl-1 text-xs text-slate-400">{alert.summary}</p>

      {open && (
        <div className="mt-3 space-y-3 rounded-xl bg-black/20 p-3">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
            <ThreatBadge label={alert.category} />
            <span>{alert.platform}</span>
            {alert.location && <span>· {alert.location}</span>}
            <button onClick={() => onOpenPost(alert.post_id)} className="ml-auto text-accent hover:underline">
              view source post →
            </button>
          </div>
          {esc?.recommended_actions && (
            <div>
              <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                Auto-generated escalation packet ({esc.priority})
              </div>
              <ul className="space-y-1 text-[11.5px] text-slate-300">
                {(esc.recommended_actions as string[]).map((a, i) => (
                  <li key={i} className="flex gap-1.5">
                    <span className="text-threat-inflammatory">▸</span> {a}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-[10px] italic text-slate-600">{esc.note}</p>
            </div>
          )}
          <div className="flex gap-2">
            {alert.status === "new" && (
              <button
                onClick={() => onAction(alert.id, "acknowledge")}
                className="inline-flex items-center gap-1.5 rounded-xl border border-accent/40 bg-accent/10 px-3 py-1.5 text-[11px] font-bold text-accent hover:bg-accent/20"
              >
                <Check size={12} /> Acknowledge
              </button>
            )}
            {alert.status !== "escalated" && (
              <button
                onClick={() => onAction(alert.id, "escalate")}
                className="inline-flex items-center gap-1.5 rounded-xl bg-threat-critical px-3 py-1.5 text-[11px] font-bold text-white hover:bg-red-600"
              >
                <Flag size={12} /> Escalate
              </button>
            )}
            {alert.status === "escalated" && (
              <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-threat-inflammatory">
                <CheckCheck size={13} /> Escalation report filed — see Reports
              </span>
            )}
          </div>
        </div>
      )}
    </GlassCard>
  );
}

export default function Alerts() {
  const [statusFilter, setStatusFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const { data, loading, refresh } = usePolling(
    () => api.alerts({ status: statusFilter || undefined, severity: severityFilter || undefined, limit: 60 }),
    20000,
    [statusFilter, severityFilter]
  );
  useLiveAlerts(); // keeps the shared socket hot so new alerts refresh fast
  const [selectedPost, setSelectedPost] = useState<Post | null>(null);
  const revealRef = useGsapReveal<HTMLDivElement>(`${statusFilter}-${severityFilter}-${data?.length ?? 0}`);

  const counts = useMemo(() => {
    const c = { critical: 0, high: 0, medium: 0, new: 0 };
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

  const openPost = async (postId: string) => {
    try {
      setSelectedPost(await api.post(postId));
    } catch { /* post may be gone */ }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-bold text-slate-200">
            <BellRing size={18} className="text-threat-critical" /> Alerts & Incidents
          </h1>
          <p className="text-xs text-slate-500">
            {counts.new} unhandled · {counts.critical} critical · {counts.high} high · {counts.medium} medium
          </p>
        </div>
        <div className="ml-auto flex gap-2 text-xs">
          <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)} className="rounded-xl border border-white/[0.08] bg-base-800 px-2.5 py-1.5 text-slate-400">
            <option value="">All severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
          </select>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="rounded-xl border border-white/[0.08] bg-base-800 px-2.5 py-1.5 text-slate-400">
            <option value="">All statuses</option>
            <option value="new">New</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="escalated">Escalated</option>
          </select>
        </div>
      </div>

      {loading && !data ? (
        <SkeletonRow n={7} />
      ) : (
        <div ref={revealRef} className="space-y-2.5">
          {data?.map((a) => (
            <AlertRow key={a.id} alert={a} onAction={act} onOpenPost={openPost} />
          ))}
          {data?.length === 0 && (
            <GlassCard className="p-10 text-center text-sm text-slate-500">No alerts match the filters.</GlassCard>
          )}
        </div>
      )}

      <DetailDrawer post={selectedPost} onClose={() => setSelectedPost(null)} />
    </div>
  );
}
