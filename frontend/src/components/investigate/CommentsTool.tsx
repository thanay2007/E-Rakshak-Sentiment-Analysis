import { useState } from "react";
import { Bot, MessagesSquare, Sparkles } from "lucide-react";
import GlassCard, { SectionTitle } from "../GlassCard";
import { api } from "../../services/api";
import type { CommentReport } from "../../services/api";
import { BOT_COLORS, EmptyHint, Pill, RunButton, SENT_COLORS, Spinner, TextInput } from "./shared";

function SentimentBar({ b }: { b: CommentReport["sentiment_breakdown"] }) {
  const segs = [
    { k: "positive", v: b.positive_pct }, { k: "neutral", v: b.neutral_pct }, { k: "negative", v: b.negative_pct },
  ];
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full">
        {segs.map((s) => s.v > 0 && (
          <div key={s.k} style={{ width: `${s.v}%`, backgroundColor: SENT_COLORS[s.k] }} title={`${s.k} ${s.v}%`} />
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-[11px]">
        {segs.map((s) => <span key={s.k} style={{ color: SENT_COLORS[s.k] }}>{s.k} {s.v}%</span>)}
      </div>
    </div>
  );
}

export default function CommentsTool() {
  const [postId, setPostId] = useState("");
  const [data, setData] = useState<CommentReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setErr(null); setLoading(true); setData(null);
    try { setData(await api.investigatePostComments(postId.trim() || "top")); }
    catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  }

  const ba = data?.bot_analysis;

  return (
    <div className="space-y-4">
      <GlassCard className="p-4">
        <SectionTitle title="Comment Analysis & Bot Detection"
          sub="Score a post's comment section for audience sentiment and automated / coordinated accounts." />
        <div className="flex items-center gap-2">
          <div className="flex-1"><TextInput value={postId} onChange={setPostId} onEnter={run} placeholder="Post ID (leave blank to analyze the top threat post)" mono /></div>
          <RunButton onClick={run} disabled={loading}><MessagesSquare size={15} /> Analyze</RunButton>
        </div>
      </GlassCard>

      {loading && <GlassCard className="p-2"><Spinner label="Reading comment thread…" /></GlassCard>}
      {err && <GlassCard className="p-4 text-sm text-red-400">Error: {err}</GlassCard>}
      {data?.error && <GlassCard className="p-4 text-sm text-amber-400">{data.error}</GlassCard>}

      {data && !data.error && !loading && (
        <>
          {data.post && (
            <GlassCard className="p-4">
              <div className="text-[11px] uppercase tracking-wide text-slate-500">{data.post.platform} · @{data.post.author_handle} · {data.post.sentiment_label}</div>
              <div className="mt-1 text-sm text-slate-200">{data.post.text}</div>
              {data.synthetic && <div className="mt-2 text-[11px] text-slate-600">Comment thread reconstructed for demo (live deployments read comments from the platform API).</div>}
            </GlassCard>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <GlassCard className="space-y-3 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-200"><Sparkles size={15} className="text-accent" /> Audience sentiment</div>
              <SentimentBar b={data.sentiment_breakdown} />
              <div className="text-[12px] text-slate-500">{data.total_comments} comments analyzed</div>
            </GlassCard>

            <GlassCard className="space-y-3 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-200"><Bot size={15} className="text-accent" /> Automation signals</div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div><div className="font-mono text-xl font-semibold text-red-400">{ba!.likely_bots}</div><div className="text-[10px] uppercase text-slate-500">likely bots</div></div>
                <div><div className="font-mono text-xl font-semibold text-amber-400">{ba!.suspicious}</div><div className="text-[10px] uppercase text-slate-500">suspicious</div></div>
                <div><div className="font-mono text-xl font-semibold text-slate-200">{ba!.suspected_pct}%</div><div className="text-[10px] uppercase text-slate-500">suspected</div></div>
              </div>
              {ba!.coordinated && <Pill color="#EF4444">⚠ Coordinated comment activity detected</Pill>}
            </GlassCard>
          </div>

          <GlassCard className="p-4">
            <div className="mb-2 text-sm font-semibold text-slate-200">Assessment</div>
            <ul className="space-y-1.5">
              {data.assessment.map((t, i) => <li key={i} className="flex gap-2 text-[13px] text-slate-300"><span className="text-accent">›</span>{t}</li>)}
            </ul>
          </GlassCard>

          <GlassCard className="p-4">
            <div className="mb-2 text-sm font-semibold text-slate-200">Comments (ranked by bot score)</div>
            <div className="space-y-1.5">
              {data.comments.slice(0, 30).map((c, i) => {
                const color = BOT_COLORS[c.bot_verdict] ?? "#64748B";
                return (
                  <div key={i} className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-mono text-[12px] text-slate-400">@{c.author_handle}</span>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <span className="text-[11px]" style={{ color: SENT_COLORS[c.sentiment_label] }}>{c.sentiment_label}</span>
                        <span className="rounded-full border px-1.5 py-0.5 text-[10px] font-mono" style={{ color, borderColor: `${color}55`, backgroundColor: `${color}14` }}>bot {c.bot_score}</span>
                      </div>
                    </div>
                    <div className="mt-1 text-[13px] text-slate-300">{c.text}</div>
                    {c.bot_verdict !== "authentic" && c.bot_signals[0] && (
                      <div className="mt-1 text-[11px] text-slate-600">{c.bot_signals.slice(0, 2).join(" · ")}</div>
                    )}
                  </div>
                );
              })}
            </div>
          </GlassCard>
        </>
      )}

      {!data && !loading && <EmptyHint>Analyze a comment thread to reveal audience sentiment and bot amplification.</EmptyHint>}
    </div>
  );
}
