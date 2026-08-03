import { useState } from "react";
import { AtSign, CheckCircle2, ExternalLink, HelpCircle, Search, ShieldAlert, XCircle } from "lucide-react";
import GlassCard, { SectionTitle } from "../GlassCard";
import { api } from "../../services/api";
import type { UsernameReport } from "../../services/api";
import { EmptyHint, RunButton, Spinner, TextInput } from "./shared";
import { safeHref } from "../../lib/safeUrl";

const STATUS_META: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  found: { color: "#10B981", icon: <CheckCircle2 size={14} />, label: "Found" },
  not_found: { color: "#64748B", icon: <XCircle size={14} />, label: "Not found" },
  blocked: { color: "#F59E0B", icon: <ShieldAlert size={14} />, label: "Blocked" },
  unknown: { color: "#A855F7", icon: <HelpCircle size={14} />, label: "Unknown" },
};

export default function UsernameTool() {
  const [u, setU] = useState("");
  const [data, setData] = useState<UsernameReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    if (!u.trim()) return;
    setErr(null); setLoading(true); setData(null);
    try {
      setData(await api.investigateUsername(u.trim()));
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  }

  return (
    <div className="space-y-4">
      <GlassCard className="p-4">
        <SectionTitle title="Username Lookup"
          sub="Enumerate a handle across social, dev and messaging platforms to map a person's online footprint." />
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <AtSign size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <div className="pl-6"><TextInput value={u} onChange={setU} onEnter={run} placeholder="handle e.g. desh_sachai_4471" mono /></div>
          </div>
          <RunButton onClick={run} disabled={loading || !u.trim()}><Search size={15} /> Search</RunButton>
        </div>
        <p className="mt-2 text-[11px] text-slate-600">
          Public, unauthenticated profile-URL probes only (no login, no scraping). Rate-limited sites resolve to “unknown”.
        </p>
      </GlassCard>

      {loading && <GlassCard className="p-2"><Spinner label={`Probing platforms for “${u}”…`} /></GlassCard>}
      {err && <GlassCard className="p-4 text-sm text-red-400">Error: {err}</GlassCard>}
      {data && !data.valid && <GlassCard className="p-4 text-sm text-amber-400">{data.error}</GlassCard>}

      {data?.valid && !loading && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(["found", "not_found", "blocked", "unknown"] as const).map((k) => (
              <GlassCard key={k} className="p-3 text-center">
                <div className="font-mono text-2xl font-semibold" style={{ color: STATUS_META[k].color }}>{data.summary[k]}</div>
                <div className="mt-0.5 text-[11px] uppercase tracking-wide text-slate-500">{STATUS_META[k].label}</div>
              </GlassCard>
            ))}
          </div>
          <GlassCard className="p-4">
            <div className="mb-2 text-[12px] text-slate-500">Checked {data.summary.checked} platforms for <span className="font-mono text-slate-300">@{data.username}</span></div>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {data.results.map((r) => {
                const m = STATUS_META[r.status] ?? STATUS_META.unknown;
                return (
                  <a key={r.site} href={safeHref(r.url)} target="_blank" rel="noreferrer"
                    className="flex items-center justify-between gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 hover:border-white/[0.15]">
                    <div className="min-w-0">
                      <div className="truncate text-[13px] text-slate-200">{r.site}</div>
                      <div className="truncate text-[11px] text-slate-600">{r.category}</div>
                    </div>
                    <span className="inline-flex shrink-0 items-center gap-1 text-[12px] font-medium" style={{ color: m.color }}>
                      {m.icon} {m.label} <ExternalLink size={11} className="text-slate-600" />
                    </span>
                  </a>
                );
              })}
            </div>
          </GlassCard>
        </>
      )}

      {!data && !loading && <EmptyHint>Enter a username to map its cross-platform presence.</EmptyHint>}
    </div>
  );
}
