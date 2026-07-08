import { Cpu, Database, KeyRound, Settings as SettingsIcon, Waves } from "lucide-react";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import { usePolling } from "../hooks/usePolling";
import { api, API_BASE } from "../services/api";

const KEY_ROWS = [
  ["X_BEARER_TOKEN", "X (Twitter) API v2 recent search"],
  ["YOUTUBE_API_KEY", "YouTube Data API v3"],
  ["REDDIT_CLIENT_ID / SECRET", "Reddit search (open JSON)"],
  ["RSS_FEEDS", "Generic web/RSS monitoring"],
];

export default function Settings() {
  const { data: health } = usePolling(() => api.health(), 30000);

  return (
    <div className="max-w-3xl space-y-4">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-bold text-slate-200">
          <SettingsIcon size={18} className="text-accent" /> System Settings
        </h1>
        <p className="text-xs text-slate-500">runtime configuration · scaling from demo to production</p>
      </div>

      <GlassCard className="p-4">
        <SectionTitle title="Runtime Status" right={<Cpu size={15} className="text-slate-600" />} />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Backend</div>
            <div className={`mt-1 font-mono text-sm font-bold ${health ? "text-threat-neutral" : "text-threat-critical"}`}>
              {health ? "ONLINE" : "UNREACHABLE"}
            </div>
            <div className="mt-0.5 truncate font-mono text-[10px] text-slate-600">{API_BASE}</div>
          </div>
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">NLP engine</div>
            <div className="mt-1 font-mono text-sm font-bold text-accent">
              {health?.nlp_mode === "full" ? "TRANSFORMER (full)" : "LITE (lexicon)"}
            </div>
            <div className="mt-0.5 text-[10px] text-slate-600">set NLP_MODE=full for XLM-R stack</div>
          </div>
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Ingestion</div>
            <div className="mt-1 font-mono text-sm font-bold text-threat-inflammatory">
              {health?.simulation ? "SIMULATED STREAM" : "LIVE APIS"}
            </div>
            <div className="mt-0.5 text-[10px] text-slate-600">zero-key demo mode active</div>
          </div>
        </div>
      </GlassCard>

      <GlassCard className="p-4">
        <SectionTitle title="Scale With Real API Keys" right={<KeyRound size={15} className="text-slate-600" />} />
        <p className="mb-3 text-xs leading-relaxed text-slate-400">
          Add any of these to <code className="rounded bg-white/10 px-1 font-mono text-[11px]">backend/.env</code> and
          restart — the matching platform adapter activates automatically and its posts flow through the
          identical NLP → scoring → alerting pipeline. No other change needed.
        </p>
        <div className="space-y-1.5">
          {KEY_ROWS.map(([k, desc]) => (
            <div key={k} className="flex items-center gap-3 rounded-xl bg-white/[0.03] px-3 py-2 text-xs">
              <code className="font-mono text-[11px] text-accent">{k}</code>
              <span className="ml-auto text-slate-500">{desc}</span>
            </div>
          ))}
        </div>
      </GlassCard>

      <GlassCard className="p-4">
        <SectionTitle title="Threat Score Formula" right={<Waves size={15} className="text-slate-600" />} />
        <pre className="overflow-x-auto rounded-xl bg-black/30 p-3 font-mono text-[11px] leading-relaxed text-slate-400">
{`score = 100 × ( 0.40 × severity(class) × confidence
              + 0.25 × toxicity
              + 0.20 × virality(engagement, amplification)
              + 0.15 × keyword_severity )

severity: Incitement 1.00 · Inflammatory 0.75 · Fake News 0.65 · Neutral 0.05
bands:    ≥74 critical alert + auto-escalation · ≥65 high · ≥50 active threat`}
        </pre>
      </GlassCard>

      <GlassCard className="p-4">
        <SectionTitle title="Data Layer" right={<Database size={15} className="text-slate-600" />} />
        <p className="text-xs leading-relaxed text-slate-400">
          SQLite by default (zero setup). For production, set{" "}
          <code className="rounded bg-white/10 px-1 font-mono text-[11px]">DATABASE_URL=postgresql+psycopg://…</code>{" "}
          — the SQLModel schema ports unchanged. Train the transformer with{" "}
          <code className="rounded bg-white/10 px-1 font-mono text-[11px]">python -m app.ml.train</code>, measure it with{" "}
          <code className="rounded bg-white/10 px-1 font-mono text-[11px]">python -m app.ml.evaluate</code>.
        </p>
      </GlassCard>
    </div>
  );
}
