import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, ExternalLink, Megaphone, MapPin } from "lucide-react";
import GlassCard, { SectionTitle } from "../GlassCard";
import { api } from "../../services/api";
import type { PrCampaign, PrReport } from "../../services/api";
import { sentimentColor } from "../../data/constants";
import { EmptyHint, Pill, Spinner } from "./shared";
import { PlatformIcon } from "../Badges";
import { usePostDetail } from "../PostDetailProvider";
import { safeHref } from "../../lib/safeUrl";

const TYPE_COLORS: Record<string, string> = {
  manufactured_outrage: "#EF4444",
  disinformation_push: "#A855F7",
  image_whitewash: "#F59E0B",
  narrative_push: "#14B8C4",
};
const WINDOWS = [24, 48, 72, 168];

/** Every account in the campaign with the posts it made — what an officer
 *  needs to act on a flag, rather than a count and one quote. */
function CampaignAccounts({ c }: { c: PrCampaign }) {
  const { openPostId } = usePostDetail();
  const established = new Set(c.established_accounts ?? []);
  const byAccount = useMemo(() => {
    const m = new Map<string, PrCampaign["sample_posts"]>();
    for (const h of c.accounts) m.set(h, []);
    for (const p of c.sample_posts) {
      const list = m.get(p.author_handle) ?? [];
      list.push(p);
      m.set(p.author_handle, list);
    }
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [c]);
  const hidden = c.posts - c.sample_posts.length;

  return (
    <div className="space-y-2 border-t border-white/[0.06] pt-3">
      {byAccount.map(([handle, posts]) => (
        <div key={handle} className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2.5">
          <div className="flex items-center gap-2 text-[13px]">
            {posts[0] && <PlatformIcon platform={posts[0].platform} size={13} />}
            <span className="font-mono font-semibold text-slate-200">@{handle}</span>
            <span className="text-slate-500">{posts.length} post{posts.length === 1 ? "" : "s"} shown</span>
            {established.has(handle) && (
              <span className="text-[12px] text-sky-400" title="Established public voice — discounted when counting independent accounts">
                established
              </span>
            )}
          </div>
          {posts.length > 0 && (
            <div className="mt-1.5 space-y-1">
              {posts.map((p) => (
                <div key={p.id} className="flex items-start gap-2">
                  <button onClick={() => openPostId(p.id)}
                    className="min-w-0 flex-1 rounded-md px-2 py-1 text-left hover:bg-white/[0.04]">
                    <div className="line-clamp-2 text-[12.5px] text-slate-300">{p.text}</div>
                    <div className="mt-0.5 text-[11.5px] text-slate-500">
                      {new Date(p.created_at).toLocaleString()} · concern {Math.round(p.concern_score)}
                      {p.sentiment_label ? ` · ${p.sentiment_label}` : ""}
                    </div>
                  </button>
                  {p.url && (
                    <a href={safeHref(p.url)} target="_blank" rel="noreferrer" title="Open on the platform"
                      className="mt-1 shrink-0 text-slate-500 hover:text-accent">
                      <ExternalLink size={13} />
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
      {hidden > 0 && (
        <p className="text-[12px] text-slate-500">
          Showing the {c.sample_posts.length} most concerning of {c.posts} posts.
        </p>
      )}
    </div>
  );
}

function CampaignCard({ c }: { c: PrCampaign }) {
  const color = TYPE_COLORS[c.type] ?? "#14B8C4";
  const [open, setOpen] = useState(false);
  return (
    <GlassCard className="space-y-3 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[13px] text-slate-500">{c.id}</span>
            <span className="text-sm font-semibold" style={{ color }}>{c.type_label}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Pill color={sentimentColor(c.law_order_category)}>{c.law_order_category}</Pill>
            <Pill color="#64748B">{c.account_count} accounts</Pill>
            <Pill color="#64748B">{c.posts} posts</Pill>
            {c.bot_ratio > 0 && <Pill color="#EF4444">{Math.round(c.bot_ratio * 100)}% bots</Pill>}
            <Pill color="#64748B">{c.sentiment_lean} lean</Pill>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="font-mono text-2xl font-semibold" style={{ color }}>{Math.round(c.confidence * 100)}%</div>
          <div className="text-xs uppercase tracking-wide text-slate-500">confidence</div>
        </div>
      </div>

      <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[13px] italic text-slate-300">“{c.sample_text}”</div>

      <div>
        <div className="mb-1 text-[13px] uppercase tracking-wide text-slate-500">Why flagged</div>
        <ul className="space-y-1">
          {c.why.map((w, i) => <li key={i} className="flex gap-2 text-[12px] text-slate-400"><span style={{ color }}>›</span>{w}</li>)}
        </ul>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-[13px] text-slate-500">
        <span>reach ≈ {c.reach_estimate.toLocaleString()}</span>
        {c.locations.length > 0 && <span className="inline-flex items-center gap-1"><MapPin size={11} />{c.locations.join(", ")}</span>}
        {c.top_hashtags.length > 0 && <span className="text-accent">{c.top_hashtags.map((t) => `#${t}`).join(" ")}</span>}
      </div>

      <button onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.1] px-3 py-1.5 text-[13px] font-medium text-slate-300 hover:border-accent/40 hover:text-accent">
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        {open ? "Hide" : "Show"} accounts & posts ({c.accounts.length} accounts · {c.posts} posts)
      </button>
      {open && <CampaignAccounts c={c} />}
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
        <SectionTitle title="Organized Online Campaigns"
          sub="Look for accounts posting together to influence public opinion on law-and-order issues."
          right={
            <div className="flex gap-1">
              {WINDOWS.map((w) => (
                <button key={w} onClick={() => setHours(w)}
                  className={`rounded-lg border px-2.5 py-1 text-[13px] font-medium ${hours === w ? "border-accent/40 bg-accent/10 text-accent" : "border-white/10 text-slate-500 hover:text-slate-300"}`}>
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
          <EmptyHint>No organized campaigns found in this time period. Try a longer period.</EmptyHint>
        )
      )}
    </div>
  );
}
