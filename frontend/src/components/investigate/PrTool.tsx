import { useEffect, useState } from "react";
import { Clock, Megaphone, MapPin, ShieldCheck, Users } from "lucide-react";
import GlassCard, { SectionTitle } from "../GlassCard";
import { PlatformIcon } from "../Badges";
import { usePostDetail } from "../PostDetailProvider";
import { api } from "../../services/api";
import type { PrCampaign, PrReport, PrSyndication } from "../../services/api";
import { sentimentColor } from "../../data/constants";
import { AiExplanation, EmptyHint, Meter, Pill, Spinner } from "./shared";

const TYPE_COLORS: Record<string, string> = {
  manufactured_outrage: "#EF4444",
  image_whitewash: "#F59E0B",
  narrative_push: "#14B8C4",
};
const WINDOWS = [24, 48, 72, 168];

function CampaignCard({ c }: { c: PrCampaign }) {
  const color = TYPE_COLORS[c.type] ?? "#14B8C4";
  const { openPostId } = usePostDetail();
  const [showAccounts, setShowAccounts] = useState(false);

  return (
    <GlassCard className="space-y-3 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-slate-500">{c.id}</span>
            <span className="text-sm font-semibold" style={{ color }}>{c.type_label}</span>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Pill color={sentimentColor(c.sentiment_lean)}>{c.sentiment_lean} lean</Pill>
            {/* "Independent" because the same organisation's handles across
                platforms are folded into one actor before counting. */}
            <Pill color="#64748B">{c.account_count} independent accounts</Pill>
            <Pill color="#64748B">{c.posts} posts</Pill>
            {c.bot_ratio > 0 && <Pill color="#EF4444">{Math.round(c.bot_ratio * 100)}% bots</Pill>}
            {c.platforms.length > 1 && <Pill color="#A855F7">{c.platforms.length} platforms</Pill>}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="font-mono text-2xl font-semibold" style={{ color }}>{Math.round(c.confidence * 100)}%</div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">confidence</div>
        </div>
      </div>

      <Meter value={Math.round(c.confidence * 100)} color={color} />

      <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[13px] italic text-slate-300">
        “{c.sample_text}”
      </div>

      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Why flagged</div>
        <ul className="space-y-1">
          {c.why.map((w, i) => (
            <li key={i} className="flex gap-2 text-[12px] text-slate-400"><span style={{ color }}>›</span>{w}</li>
          ))}
        </ul>
      </div>

      {/* The actual posts, openable — a campaign card with no way to read the
          evidence is an assertion the analyst cannot check. */}
      {c.sample_posts.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
            Evidence · highest concern first
          </div>
          <div className="space-y-1">
            {c.sample_posts.map((p) => (
              <button key={p.id} onClick={() => openPostId(p.id)}
                className="flex w-full items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5 text-left transition-colors hover:border-white/[0.16]">
                <PlatformIcon platform={p.platform} size={13} />
                <span className="shrink-0 font-mono text-[11px] text-slate-500">@{p.author_handle}</span>
                <span className="min-w-0 flex-1 truncate text-[11.5px] text-slate-300">{p.text}</span>
                <span className="shrink-0 font-mono text-[10px] text-slate-500">{Math.round(p.concern_score)}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-white/[0.06] pt-2 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1">
          <Clock size={11} />posted over {c.spread_minutes < 60 ? `${c.spread_minutes}m` : `${Math.round(c.spread_minutes / 60)}h`}
        </span>
        <span>reach ≈ {c.reach_estimate.toLocaleString()}</span>
        <span>avg concern {c.avg_concern}</span>
        {c.locations.length > 0 && (
          <span className="inline-flex items-center gap-1"><MapPin size={11} />{c.locations.join(", ")}</span>
        )}
        {c.top_hashtags.length > 0 && (
          <span className="text-accent">{c.top_hashtags.map((t) => `#${t}`).join(" ")}</span>
        )}
        <button onClick={() => setShowAccounts((s) => !s)}
          className="ml-auto inline-flex items-center gap-1 text-slate-400 hover:text-accent">
          <Users size={11} /> {showAccounts ? "hide" : "show"} roster
        </button>
      </div>

      {showAccounts && (
        <div className="flex flex-wrap gap-1">
          {c.accounts.map((a) => (
            <span key={a} className="rounded-md border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 font-mono text-[10.5px] text-slate-400">
              @{a}
            </span>
          ))}
        </div>
      )}
    </GlassCard>
  );
}

export default function PrTool() {
  const [hours, setHours] = useState(72);
  const [minAccounts, setMinAccounts] = useState(3);
  const [data, setData] = useState<PrReport | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.investigatePrCampaigns(hours, minAccounts)
      .then((d) => { if (alive) setData(d); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [hours, minAccounts]);

  return (
    <div className="space-y-4">
      <GlassCard className="p-4">
        <SectionTitle
          title="Coordinated Campaign Detection"
          sub="Groups of accounts posting almost the same words at the same time — usually an organised or paid push."
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

        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-[12px] text-slate-400">
            Cluster size ≥
            <input type="range" min={2} max={10} value={minAccounts}
              onChange={(e) => setMinAccounts(Number(e.target.value))}
              className="w-28 accent-[#14B8C4]" />
            <span className="w-16 font-mono text-slate-200">{minAccounts} accounts</span>
          </label>
          {data && (
            <div className="flex items-center gap-2 text-[12.5px] text-slate-400">
              <Megaphone size={15} className="text-accent" />
              {data.campaigns_found} campaign{data.campaigns_found === 1 ? "" : "s"} in the last{" "}
              {hours < 72 ? `${hours}h` : `${hours / 24} days`}
            </div>
          )}
        </div>

        {/* Every cluster the detector saw has to be accounted for here. Without
            it, an empty result is ambiguous between "nothing coordinated",
            "nothing ran", and "it found things and threw them away". */}
        {data && !loading && (
          <p className="mt-2 text-[11px] text-slate-600">
            Scanned {data.posts_scanned.toLocaleString()} posts · {data.clusters_found} near-duplicate
            cluster{data.clusters_found === 1 ? "" : "s"} found
            {data.neutral_clusters_ignored > 0 &&
              ` · ${data.neutral_clusters_ignored} neutral (ordinary announcements)`}
            {!!data.syndication_ignored &&
              ` · ${data.syndication_ignored} official/verified syndication`}
            {!!data.weak_clusters_ignored &&
              ` · ${data.weak_clusters_ignored} with no sign of coordination beyond shared wording`}
          </p>
        )}
        {data && !loading && <p className="mt-1 text-[11px] text-slate-600">{data.note}</p>}
      </GlassCard>

      {loading && <GlassCard className="p-2"><Spinner label="Clustering near-duplicate copy across the window…" /></GlassCard>}

      {data && !loading && (
        data.campaigns.length ? (
          <>
            <AiExplanation tool="pr" report={data} deps={[hours, minAccounts, data.campaigns_found]} />
            <div className="grid gap-4 xl:grid-cols-2">
              {data.campaigns.map((c) => <CampaignCard key={c.id} c={c} />)}
            </div>
          </>
        ) : (
          <EmptyHint>
            No coordinated campaign in this window. {data.clusters_found > 0
              ? `${data.clusters_found} cluster(s) matched on wording, but none of them held up as an organised push — see the breakdown above.`
              : "Try a wider window or a smaller cluster size."}
          </EmptyHint>
        )
      )}

      {data && !loading && !!data.syndication?.length && <SyndicationPanel items={data.syndication} />}
    </div>
  );
}

/** Clusters that duplicate copy but are not campaigns — official desks and
 *  verified accounts carrying the same notice. Shown rather than dropped: an
 *  officer who can see the duplication in the feed needs to know the detector
 *  saw it too and what it concluded, otherwise "no campaigns" looks broken. */
function SyndicationPanel({ items }: { items: PrSyndication[] }) {
  const [open, setOpen] = useState(false);
  return (
    <GlassCard className="p-4">
      <button onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 text-left text-[13px] font-semibold text-slate-300 hover:text-slate-100">
        <ShieldCheck size={14} className="text-emerald-400" />
        {items.length} cluster{items.length === 1 ? "" : "s"} of duplicated copy set aside as legitimate syndication
        <span className="ml-auto text-[11px] font-normal text-slate-500">{open ? "hide" : "show"}</span>
      </button>
      <p className="mt-1 text-[11px] text-slate-600">
        Same words, many handles — but the accounts behind them are official desks, verified accounts, or one
        organisation posting to its own several platforms. That is a press release travelling, not an organised push.
      </p>
      {open && (
        <div className="mt-3 space-y-2">
          {items.map((s) => (
            <div key={s.id} className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
              <div className="flex flex-wrap items-center gap-1.5">
                {s.accounts.slice(0, 6).map((a) => (
                  <span key={a} className="rounded-md border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 font-mono text-[10.5px] text-slate-400">@{a}</span>
                ))}
                <span className="text-[11px] text-slate-600">· {s.posts} posts · {s.platforms.join(", ")}</span>
              </div>
              <div className="mt-1 truncate text-[12px] italic text-slate-400">“{s.sample_text}”</div>
              <div className="mt-1 text-[11px] text-emerald-400/80">{s.why}</div>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
}
