import { BrainCircuit, CheckCircle2, Layers, ShieldCheck } from "lucide-react";
import GlassCard, { SectionTitle } from "./GlassCard";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import type { ModelCard } from "../services/api";

const FAMILY_COLOR: Record<string, string> = {
  "Deep learning (fine-tuned)": "#14B8C4",
  "Classical machine learning": "#A855F7",
  "Rule-based": "#F59E0B",
};

function Card({ m, idx }: { m: ModelCard; idx: number }) {
  const acc = m.accuracy?.accuracy;
  const color = FAMILY_COLOR[m.family] ?? "#64748B";
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[11px] font-bold text-slate-600">#{idx + 1}</span>
        <span className="text-[13px] font-semibold text-slate-100">{m.name}</span>
        {m.live && (
          <span className="inline-flex items-center gap-1 rounded-md bg-threat-neutral/15 px-1.5 py-0.5 text-[9px] font-bold text-threat-neutral">
            <CheckCircle2 size={9} /> LOADED
          </span>
        )}
        <span className="ml-auto rounded-md px-1.5 py-0.5 text-[9.5px] font-semibold" style={{ backgroundColor: `${color}22`, color }}>
          {m.family}
        </span>
      </div>
      {m.base_model && <div className="mt-1 font-mono text-[10.5px] text-slate-500">{m.base_model}</div>}
      <p className="mt-1.5 text-[11.5px] leading-relaxed text-slate-400">{m.approach}</p>

      <div className="mt-2 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-lg bg-white/[0.03] p-1.5">
          <div className="font-mono text-base font-bold" style={{ color }}>
            {acc != null ? `${(acc * 100).toFixed(1)}%` : "—"}
          </div>
          <div className="text-[8.5px] uppercase tracking-widest text-slate-500">accuracy</div>
        </div>
        <div className="rounded-lg bg-white/[0.03] p-1.5">
          <div className="font-mono text-base font-bold text-slate-200">
            {m.training_data?.train_rows ? m.training_data.train_rows.toLocaleString() : "—"}
          </div>
          <div className="text-[8.5px] uppercase tracking-widest text-slate-500">train rows</div>
        </div>
        <div className="rounded-lg bg-white/[0.03] p-1.5">
          <div className="font-mono text-base font-bold text-slate-200">
            {m.accuracy?.macro_f1 != null ? m.accuracy.macro_f1.toFixed(2) : "—"}
          </div>
          <div className="text-[8.5px] uppercase tracking-widest text-slate-500">macro-F1</div>
        </div>
      </div>

      {m.per_language && Object.keys(m.per_language).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {Object.entries(m.per_language)
            .filter(([lang]) => lang !== "Overall")
            .map(([lang, s]) => (
              <span key={lang} className="rounded-md bg-white/[0.04] px-1.5 py-0.5 font-mono text-[9.5px] text-slate-400">
                {lang} {(s.accuracy * 100).toFixed(0)}%
              </span>
            ))}
        </div>
      )}
      {m.training_data?.sources && (
        <p className="mt-1.5 text-[10px] leading-relaxed text-slate-600">{m.training_data.sources}</p>
      )}
      {m.strength && (
        <p className="mt-1 text-[10.5px] italic text-slate-500">→ {m.strength}</p>
      )}
    </div>
  );
}

export default function ModelsPanel() {
  const { data } = usePolling(() => api.models(), 60000);
  if (!data) return null;

  return (
    <GlassCard className="p-4">
      <SectionTitle
        title="3-Model Consensus Engine"
        sub="each post scored by three independent models · best chosen · Groq-verified"
        right={<BrainCircuit size={15} className="text-accent" />}
      />

      <div className="mb-3 flex items-start gap-2 rounded-xl border border-accent/20 bg-accent/[0.05] p-3">
        <Layers size={16} className="mt-0.5 shrink-0 text-accent" />
        <p className="text-[11.5px] leading-relaxed text-slate-400">{data.ensemble.decision_rule}</p>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        {data.ensemble.models.map((m, i) => <Card key={m.id} m={m} idx={i} />)}
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {/* threat model */}
        <div className="rounded-xl border border-threat-high/25 bg-threat-high/[0.03] p-3">
          <div className="flex items-center gap-2">
            <ShieldCheck size={14} className="text-threat-high" />
            <span className="text-[12.5px] font-semibold text-slate-100">{data.threat_model.name}</span>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{data.threat_model.approach}</p>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {data.threat_model.labels.map((l) => (
              <span key={l} className="rounded-md bg-white/[0.05] px-1.5 py-0.5 text-[9.5px] text-slate-400">{l}</span>
            ))}
          </div>
          {data.threat_model.accuracy?.accuracy != null && (
            <div className="mt-1.5 font-mono text-[10.5px] text-slate-500">
              eval accuracy {(data.threat_model.accuracy.accuracy * 100).toFixed(0)}% ·{" "}
              {data.threat_model.eval_samples} curated samples
            </div>
          )}
        </div>
        {/* verification */}
        <div className="rounded-xl border border-threat-neutral/25 bg-threat-neutral/[0.03] p-3">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={14} className="text-threat-neutral" />
            <span className="text-[12.5px] font-semibold text-slate-100">{data.verification.layer}</span>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{data.verification.role}</p>
        </div>
      </div>

      <p className="mt-2 text-right text-[10px] text-slate-600">
        Full write-up: docs/MODELS.md · figures read live from eval reports
      </p>
    </GlassCard>
  );
}
