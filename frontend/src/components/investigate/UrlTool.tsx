import { useState } from "react";
import { ArrowRight, Link2, ShieldAlert } from "lucide-react";
import GlassCard, { SectionTitle } from "../GlassCard";
import { api } from "../../services/api";
import type { UrlReport } from "../../services/api";
import { EmptyHint, FindingRow, LEVEL_COLORS, Meter, Pill, RunButton, Spinner, TextInput } from "./shared";

export default function UrlTool() {
  const [url, setUrl] = useState("");
  const [data, setData] = useState<UrlReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    if (!url.trim()) return;
    setErr(null); setLoading(true); setData(null);
    try { setData(await api.investigateUrl(url.trim(), true)); }
    catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  }

  const riskColor = data?.risk_level ? LEVEL_COLORS[data.risk_level] ?? "#64748B" : "#64748B";

  return (
    <div className="space-y-4">
      <GlassCard className="p-4">
        <SectionTitle title="Link & URL Analysis"
          sub="Unwrap shortened / cloaked links and score them for phishing and obfuscation signals." />
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Link2 size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <div className="pl-6"><TextInput value={url} onChange={setUrl} onEnter={run} placeholder="https://bit.ly/… or any suspicious link" mono /></div>
          </div>
          <RunButton onClick={run} disabled={loading || !url.trim()}><ShieldAlert size={15} /> Analyze</RunButton>
        </div>
      </GlassCard>

      {loading && <GlassCard className="p-2"><Spinner label="Resolving redirects & scoring…" /></GlassCard>}
      {err && <GlassCard className="p-4 text-sm text-red-400">Error: {err}</GlassCard>}
      {data && !data.valid && <GlassCard className="p-4 text-sm text-amber-400">{data.error}</GlassCard>}

      {data?.valid && !loading && (
        <div className="grid gap-4 lg:grid-cols-2">
          <GlassCard className="space-y-3 p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-200">Risk verdict</span>
              <Pill color={riskColor}>{data.risk_level?.toUpperCase()}</Pill>
            </div>
            <Meter value={data.risk_score ?? 0} color={riskColor} label="Risk score" />
            <div className="space-y-1 pt-1">
              {Object.entries(data.meta ?? {}).filter(([, v]) => typeof v !== "boolean").map(([k, v]) => (
                <div key={k} className="flex items-baseline justify-between border-b border-white/[0.05] py-1 text-[12px] last:border-0">
                  <span className="uppercase tracking-wide text-slate-500">{k.replace(/_/g, " ")}</span>
                  <span className="font-mono text-slate-300">{String(v)}</span>
                </div>
              ))}
            </div>
          </GlassCard>

          <GlassCard className="space-y-3 p-4">
            <span className="text-sm font-semibold text-slate-200">Redirect chain</span>
            {data.redirect?.chain.length ? (
              <div className="space-y-1.5">
                {data.redirect.chain.map((h, i) => (
                  <div key={i} className="flex items-center gap-2 text-[12px]">
                    <span className="font-mono text-slate-500">{h.status}</span>
                    <ArrowRight size={11} className="text-slate-600" />
                    <span className="truncate font-mono text-slate-300">{h.url}</span>
                  </div>
                ))}
                {data.redirect.final_url && (
                  <div className="mt-2 rounded-lg border border-accent/20 bg-accent/[0.06] px-3 py-2 text-[12px] text-accent">
                    Final destination: <span className="font-mono">{data.redirect.final_url}</span>
                  </div>
                )}
              </div>
            ) : (
              <EmptyHint>{data.redirect?.reason || "Redirects not resolved."}</EmptyHint>
            )}
          </GlassCard>

          <GlassCard className="space-y-1.5 p-4 lg:col-span-2">
            <span className="text-sm font-semibold text-slate-200">Signals</span>
            <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
              {data.findings?.map((f, i) => <FindingRow key={i} level={f.level} text={f.text} on={f.on} />)}
            </div>
          </GlassCard>
        </div>
      )}

      {!data && !loading && <EmptyHint>Paste a link — shorteners are unwrapped to their true destination before scoring.</EmptyHint>}
    </div>
  );
}
