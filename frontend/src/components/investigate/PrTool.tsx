import { useEffect, useState } from "react";
import { Megaphone, MapPin } from "lucide-react";
import GlassCard, { SectionTitle } from "../GlassCard";
import { api } from "../../services/api";
import type { PrCampaign, PrReport } from "../../services/api";
import { THREAT_COLORS } from "../../data/constants";
import { EmptyHint, Pill, Spinner } from "./shared";

const TYPE_COLORS: Record<string, string> = {
  manufactured_outrage: "#EF4444",
  disinformation_push: "#A855F7",
  image_whitewash: "#F59E0B",
  narrative_push: "#14B8C4",
};
const WINDOWS = [24, 48, 72, 168];

function CampaignCard({ c }: { c: PrCampaign }) {
  const color = TYPE_COLORS[c.type] ?? "#14B8C4";
  return (
    <GlassCard className="space-y-3 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-slate-500">{c.id}</span>
            <span className="text-sm font-semibold" style={{ color }}>{c.type_label}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Pill color={THREAT_COLORS[c.law_order_category] ?? "#64748B"}>{c.law_order_category}</Pill>
            <Pill color="#64748B">{c.account_count} accounts</Pill>
            <Pill color="#64748B">{c.posts} posts</Pill>
            {c.bot_ratio > 0 && <Pill color="#EF4444">{Math.round(c.bot_ratio * 100)}% bots</Pill>}
            <Pill color="#64748B">{c.sentiment_lean} lean</Pill>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="font-mono text-2xl font-semibold" style={{ color }}>{Math.round(c.confidence * 100)}%</div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">confidence</div>
        </div>
      </div>

      <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[13px] italic text-slate-300">“{c.sample_text}”</div>

      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Why flagged</div>
        <ul className="space-y-1">
          {c.why.map((w, i) => <li key={i} className="flex gap-2 text-[12px] text-slate-400"><span style={{ color }}>›</span>{w}</li>)}
        </ul>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
        <span>reach ≈ {c.reach_estimate.toLocaleString()}</span>
        {c.locations.length > 0 && <span className="inline-flex items-center gap-1"><MapPin size={11} />{c.locations.join(", ")}</span>}
        {c.top_hashtags.length > 0 && <span className="text-accent">{c.top_hashtags.map((t) => `#${t}`).join(" ")}</span>}
      </div>
    </GlassCard>
  );
}

export default function PrTool() {
  const [hours, setHours] = useState(72);
  const [data, setData] = useState<PrReport | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.investigatePrCampaigns(hours).then((d) => { if (alive) setData(d); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [hours]);

  return (
    <div className="space-y-4">
      <GlassCard className="p-4">
        <SectionTitle title="Fake PR Campaign Analysis"
          sub="Coordinated inauthentic messaging that manufactures a narrative — scoped to law-and-order impact."
          right={
            <div className="flex gap-1">
              {WINDOWS.map((w) => (
                <button key={w} onClick={() => setHours(w)}
                  className={`rounded-lg border px-2.5 py-1 text-[11px] font-medium ${hours === w ? "border-accent/40 bg-accent/10 text-accent" : "border-white/10 text-slate-500 hover:text-slate-300"}`}>
                  {w < 72 ? `${w}h` : `${w / 24}d`}
                </button>
              ))}
            </div>
          } />
        {data && <div className="flex items-center gap-2 text-[13px] text-slate-400"><Megaphone size={15} className="text-accent" /> {data.campaigns_found} campaign(s) with law-and-order impact in the last {hours < 72 ? `${hours}h` : `${hours / 24} days`}</div>}
      </GlassCard>

      {loading && <GlassCard className="p-2"><Spinner label="Scanning for coordinated campaigns…" /></GlassCard>}

      {data && !loading && (
        data.campaigns.length ? (
          <div className="grid gap-4 xl:grid-cols-2">
            {data.campaigns.map((c) => <CampaignCard key={c.id} c={c} />)}
          </div>
        ) : (
          <EmptyHint>No coordinated law-and-order PR campaigns detected in this window. Try a wider window.</EmptyHint>
        )
      )}
    </div>
  );
}
