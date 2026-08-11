import { useState } from "react";
import { Fingerprint, Globe, ShieldAlert, UserSearch } from "lucide-react";
import GlassCard, { SectionTitle } from "../GlassCard";
import { api } from "../../services/api";
import type { Dossier } from "../../services/api";
import { sentimentColor } from "../../data/constants";
import { usePostDetail } from "../PostDetailProvider";
import { BOT_COLORS, EmptyHint, KV, Meter, Pill, RunButton, Spinner, TextInput } from "./shared";
import { safeHref } from "../../lib/safeUrl";

export default function SleuthTool() {
  const { openPostId } = usePostDetail();
  const [handle, setHandle] = useState("");
  const [data, setData] = useState<Dossier | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    if (!handle.trim()) return;
    setErr(null); setLoading(true); setData(null);
    try { setData(await api.investigateSleuth(handle.trim(), true)); }
    catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  }

  const auth = data?.authenticity;
  const authColor = auth ? BOT_COLORS[auth.verdict] ?? "#64748B" : "#64748B";

  return (
    <div className="space-y-4">
      <GlassCard className="p-4">
        <SectionTitle title="Social Sleuth — Account Dossier"
          sub="Fuse an account's corpus footprint, authenticity score, coordination and cross-platform presence into one profile." />
        <div className="flex items-center gap-2">
          <div className="flex-1"><TextInput value={handle} onChange={setHandle} onEnter={run} placeholder="account handle to profile" mono /></div>
          <RunButton onClick={run} disabled={loading || !handle.trim()}><UserSearch size={15} /> Build dossier</RunButton>
        </div>
      </GlassCard>

      {loading && <GlassCard className="p-2"><Spinner label="Compiling dossier…" /></GlassCard>}
      {err && <GlassCard className="p-4 text-sm text-red-400">Error: {err}</GlassCard>}

      {data && !loading && (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            {/* authenticity */}
            <GlassCard className="space-y-3 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-200"><ShieldAlert size={15} className="text-accent" /> Authenticity</div>
              <div className="text-center">
                <div className="font-mono text-3xl font-semibold" style={{ color: authColor }}>{auth!.score}</div>
                <Pill color={authColor}>{auth!.verdict.replace("_", " ")}</Pill>
              </div>
              <Meter value={auth!.score} color={authColor} />
              <ul className="space-y-1">
                {auth!.signals.map((s, i) => <li key={i} className="text-[11px] text-slate-500">· {s}</li>)}
              </ul>
            </GlassCard>

            {/* profile */}
            <GlassCard className="space-y-2 p-4 lg:col-span-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-200"><Fingerprint size={15} className="text-accent" /> @{data.handle}</div>
              {data.found && data.profile ? (
                <div className="grid gap-x-6 sm:grid-cols-2">
                  <KV k="Name" v={data.profile.author_name || "—"} />
                  <KV k="Followers" v={data.profile.followers.toLocaleString()} />
                  <KV k="Verified" v={data.profile.verified ? "yes" : "no"} />
                  <KV k="Account age" v={`${data.profile.account_age_days} d`} />
                  <KV k="Posts tracked" v={data.activity!.posts_tracked} />
                  <KV k="Posts / day" v={data.activity!.posts_per_day} />
                  <KV k="Platforms" v={data.profile.platforms.join(", ")} />
                  <KV k="Languages" v={data.profile.languages.join(", ")} />
                  <KV k="Avg threat" v={data.threat_profile!.avg_concern_score} />
                  <KV k="In cluster" v={data.coordination!.in_cluster ? data.coordination!.cluster_ids.join(", ") : "no"} />
                </div>
              ) : (
                <EmptyHint>{data.note || "No corpus footprint for this handle."}</EmptyHint>
              )}
            </GlassCard>
          </div>

          {data.found && data.threat_profile && (
            <GlassCard className="p-4">
              <div className="mb-2 text-sm font-semibold text-slate-200">Threat footprint</div>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(data.threat_profile.label_breakdown).map(([k, v]) => (
                  <Pill key={k} color={sentimentColor(k)}>{k}: {v}</Pill>
                ))}
              </div>
              {data.notable_posts && data.notable_posts.length > 0 && (
                <div className="mt-3 space-y-1.5">
                  {data.notable_posts.map((p, i) => (
                    <button
                      key={p.id ?? i}
                      onClick={() => p.id && openPostId(p.id)}
                      disabled={!p.id}
                      className="w-full rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-left transition-colors enabled:hover:border-accent/40 enabled:hover:bg-white/[0.05] disabled:cursor-default"
                    >
                      <div className="flex items-center justify-between text-[11px]">
                        <span className="text-slate-500">{p.platform}</span>
                        <span style={{ color: sentimentColor(p.sentiment_label) }}>{p.sentiment_label} · {p.concern_score}</span>
                      </div>
                      <div className="mt-1 text-[13px] text-slate-300">{p.text}</div>
                      {p.id && (
                        <span className="mt-1 block text-[10.5px] font-semibold text-accent">open full detail →</span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </GlassCard>
          )}

          {data.cross_platform?.valid && (
            <GlassCard className="p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-200"><Globe size={15} className="text-accent" /> Cross-platform presence</div>
              <div className="mb-2 text-[12px] text-slate-500">
                Found on {data.cross_platform.summary.found} of {data.cross_platform.summary.checked} platforms
              </div>
              <div className="flex flex-wrap gap-1.5">
                {data.cross_platform.results.filter((r) => r.status === "found").map((r) => (
                  <a key={r.site} href={safeHref(r.url)} target="_blank" rel="noreferrer"
                    className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[12px] text-emerald-400 hover:bg-emerald-500/20">
                    {r.site}
                  </a>
                ))}
                {data.cross_platform.summary.found === 0 && <span className="text-[12px] text-slate-600">No confirmed profiles (or probes were rate-limited).</span>}
              </div>
            </GlassCard>
          )}
        </>
      )}

      {!data && !loading && <EmptyHint>Enter a handle to compile a full investigative dossier.</EmptyHint>}
    </div>
  );
}
