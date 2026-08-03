import {
  Bot, Cpu, Database, Download, KeyRound, Languages, Play, RefreshCcw,
  Settings as SettingsIcon, Trash2, Waves, Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import ModelsPanel from "../components/ModelsPanel";
import { usePolling } from "../hooks/usePolling";
import { api, API_BASE } from "../services/api";

const KEY_ROWS = [
  ["X_AUTH_TOKEN / X_CT0", "X (Twitter) via twikit session cookies"],
  ["X_BEARER_TOKEN", "X (Twitter) official API v2 (paid)"],
  ["REDDIT_CLIENT_ID / SECRET", "Reddit official API (keyless PullPush fallback active)"],
  ["FB_ACCESS_TOKEN / FB_PAGE_IDS", "Facebook Graph API seed pages"],
  ["IG_ACCESS_TOKEN / IG_SEED_USERNAMES", "Instagram Graph API seed accounts"],
  ["TELEGRAM_API_ID / HASH / SESSION_STRING", "Telegram MTProto full channel reads (keyless t.me previews active)"],
  ["YOUTUBE_API_KEY", "YouTube Data API v3 — video search + comments (10,000 quota units/day)"],
];

function fmtUptime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export default function Settings() {
  const { data: sys, refresh } = usePolling(() => api.systemStatus(), 15000);
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [purgeDays, setPurgeDays] = useState(30);
  const [purgeArmed, setPurgeArmed] = useState(false);
  const [retrain, setRetrain] = useState<string | null>(null);
  const retrainTimer = useRef<number | null>(null);

  const run = async (name: string, fn: () => Promise<string>) => {
    setBusy(name);
    setResult(null);
    try {
      setResult(await fn());
      refresh();
    } catch (e) {
      setResult(`${name} failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const stopRetrainPoll = () => {
    if (retrainTimer.current) window.clearInterval(retrainTimer.current);
    retrainTimer.current = null;
  };

  const pollRetrain = () => {
    stopRetrainPoll();
    let inFlight = false;
    retrainTimer.current = window.setInterval(async () => {
      if (inFlight) return; // a slow status call must not stack up behind itself
      inFlight = true;
      try {
        const s = await api.retrainStatus();
        if (s.state === "running") {
          setRetrain(`training… ${s.elapsed_seconds}s`);
        } else {
          stopRetrainPoll();
          setRetrain(s.state === "done" ? `done in ${s.elapsed_seconds}s — model reloaded` : `failed (exit ${s.exit_code})`);
        }
      } catch (e) {
        // without this the rejection goes unhandled and the interval polls forever
        stopRetrainPoll();
        setRetrain(`status check failed: ${e instanceof Error ? e.message : String(e)}`);
      } finally {
        inFlight = false;
      }
    }, 3000);
  };
  useEffect(() => stopRetrainPoll, []);

  const llmModels = sys?.llm?.models ?? [];
  const db = sys?.database;

  return (
    <div className="max-w-4xl space-y-4">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-bold text-slate-200">
          <SettingsIcon size={18} className="text-accent" /> System
        </h1>
        <p className="text-xs text-slate-500">operations console · live diagnostics and maintenance actions</p>
      </div>

      {/* runtime status */}
      <GlassCard className="p-4">
        <SectionTitle title="Runtime Status" right={<Cpu size={15} className="text-slate-600" />} />
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Backend</div>
            <div className={`mt-1 font-mono text-sm font-bold ${sys ? "text-threat-neutral" : "text-threat-critical"}`}>
              {sys ? "ONLINE" : "UNREACHABLE"}
            </div>
            <div className="mt-0.5 truncate font-mono text-[10px] text-slate-600">
              {sys ? `up ${fmtUptime(sys.uptime_seconds)}` : API_BASE}
            </div>
          </div>
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">NLP engine</div>
            <div className="mt-1 font-mono text-sm font-bold text-accent">
              {sys?.nlp_mode === "full" ? "TRANSFORMER" : "LITE (lexicon)"}
            </div>
            <div className="mt-0.5 text-[10px] text-slate-600">3-model consensus + LLM review</div>
          </div>
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Ingestion</div>
            <div className="mt-1 font-mono text-sm font-bold text-threat-inflammatory">
              {sys?.simulation ? "SIMULATED" : "LIVE APIS"}
            </div>
            <div className="mt-0.5 text-[10px] text-slate-600">
              {sys?.scheduler_running ? `tick every ${sys.ingest_interval_seconds}s` : "scheduler stopped"}
            </div>
          </div>
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Database</div>
            <div className="mt-1 font-mono text-sm font-bold text-slate-200">
              {db ? `${db.counts.posts.toLocaleString()} posts` : "—"}
            </div>
            <div className="mt-0.5 text-[10px] text-slate-600">
              {db?.size_mb != null ? `${db.size_mb} MB · ${db.counts.alerts} alerts · ${db.counts.reports} reports` : ""}
            </div>
          </div>
        </div>
      </GlassCard>

      {/* LLM layer */}
      <GlassCard className="p-4">
        <SectionTitle
          title="LLM Layer (Groq)"
          sub="per-model rate-limit status — calls walk this chain top to bottom"
          right={<Bot size={15} className="text-slate-600" />}
        />
        {!sys?.llm?.enabled ? (
          <p className="text-xs text-slate-500">GROQ_API_KEY not configured — verification, translation and dossiers are off.</p>
        ) : (
          <div className="space-y-1.5">
            {llmModels.map((m) => (
              <div key={m.model} className="flex items-center gap-3 rounded-xl bg-white/[0.03] px-3 py-2 text-xs">
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${m.state === "ready" ? "bg-threat-neutral" : "bg-threat-critical"}`}
                />
                <code className="font-mono text-[11px] text-slate-200">{m.model}</code>
                <span className="rounded-full bg-white/[0.06] px-2 py-px text-[9px] uppercase tracking-wider text-slate-500">
                  {m.role}
                </span>
                <span className="ml-auto text-[10.5px] text-slate-500">
                  {m.state === "cooling_down"
                    ? `rate-limited — retry in ${Math.ceil(m.cooldown_seconds_left / 60)}m`
                    : m.last_ok
                      ? "ready"
                      : "untested"}
                </span>
              </div>
            ))}
          </div>
        )}
        <button
          onClick={() =>
            run("LLM test", async () => {
              const r = await api.testLlm();
              return r.ok ? `LLM online — ${r.model} answered in ${r.latency_ms}ms` : `LLM unavailable: ${r.error}`;
            })
          }
          disabled={busy !== null}
          className="mt-3 inline-flex items-center gap-1.5 rounded-xl border border-accent/50 bg-accent/15 px-3.5 py-2 text-xs font-bold text-accent hover:bg-accent hover:text-base-900 disabled:opacity-50"
        >
          <Zap size={13} /> {busy === "LLM test" ? "Testing…" : "Test connection"}
        </button>
      </GlassCard>

      {/* operations */}
      <GlassCard className="p-4">
        <SectionTitle
          title="Operations"
          sub="maintenance actions — run directly against the live system"
          right={<Play size={15} className="text-slate-600" />}
        />
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => run("Crawl", async () => {
              const r = await api.crawlNow();
              return `Crawl tick complete — ${r.new_posts} new posts ingested`;
            })}
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.1] bg-white/[0.05] px-3.5 py-2 text-xs font-semibold text-slate-200 hover:border-accent/40 hover:text-accent disabled:opacity-50"
          >
            <RefreshCcw size={13} /> {busy === "Crawl" ? "Crawling…" : "Crawl now"}
          </button>
          <button
            onClick={() => run("Translate", async () => {
              const r = await api.translateMissing(60);
              return `Translated ${r.translated} posts — ${r.remaining_candidates} still untranslated`;
            })}
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.1] bg-white/[0.05] px-3.5 py-2 text-xs font-semibold text-slate-200 hover:border-accent/40 hover:text-accent disabled:opacity-50"
          >
            <Languages size={13} />
            {busy === "Translate" ? "Translating…" : `Backfill translations${db ? ` (${db.untranslated_posts})` : ""}`}
          </button>
          <button
            onClick={() => run("Relabel", async () => {
              const r = await api.relabelLanguages();
              return `Language re-detection: ${r.relabeled} posts relabeled`;
            })}
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.1] bg-white/[0.05] px-3.5 py-2 text-xs font-semibold text-slate-200 hover:border-accent/40 hover:text-accent disabled:opacity-50"
          >
            <Languages size={13} /> {busy === "Relabel" ? "Scanning…" : "Re-detect languages"}
          </button>
          <button
            onClick={async () => {
              setRetrain("starting…");
              try {
                await api.retrainBaseline();
                pollRetrain();
              } catch (e) {
                setRetrain(`failed to start: ${e instanceof Error ? e.message : e}`);
              }
            }}
            disabled={retrain?.startsWith("training") ?? false}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.1] bg-white/[0.05] px-3.5 py-2 text-xs font-semibold text-slate-200 hover:border-accent/40 hover:text-accent disabled:opacity-50"
          >
            <Cpu size={13} /> Retrain classical model
          </button>
        </div>
        {retrain && <p className="mt-2 font-mono text-[11px] text-accent">retrain: {retrain}</p>}
        {result && <p className="mt-2 text-[11.5px] font-medium text-threat-neutral">{result}</p>}
      </GlassCard>

      {/* data tools */}
      <GlassCard className="p-4">
        <SectionTitle title="Data" sub="export for records · retention purge" right={<Database size={15} className="text-slate-600" />} />
        <div className="flex flex-wrap items-center gap-2">
          {[24, 24 * 7].map((h) => (
            <button
              key={h}
              onClick={() => void api.downloadPostsCsv(h)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.1] bg-white/[0.05] px-3.5 py-2 text-xs font-semibold text-slate-200 hover:border-accent/40 hover:text-accent"
            >
              <Download size={13} /> Posts CSV · last {h === 24 ? "24h" : "7d"}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-2">
            <span className="text-[11px] text-slate-500">purge posts older than</span>
            <input
              type="number"
              min={1}
              max={365}
              value={purgeDays}
              onChange={(e) => { setPurgeDays(Number(e.target.value)); setPurgeArmed(false); }}
              className="w-16 rounded-lg border border-white/[0.08] bg-white/[0.04] px-2 py-1.5 text-center font-mono text-xs text-slate-200 focus:border-accent/40 focus:outline-none"
            />
            <span className="text-[11px] text-slate-500">days</span>
            <button
              onClick={() => {
                if (!purgeArmed) { setPurgeArmed(true); return; }
                setPurgeArmed(false);
                run("Purge", async () => {
                  const r = await api.purgePosts(purgeDays);
                  return `Purged ${r.deleted} posts older than ${purgeDays} days`;
                });
              }}
              disabled={busy !== null}
              className={`inline-flex items-center gap-1.5 rounded-xl border px-3.5 py-2 text-xs font-bold disabled:opacity-50 ${
                purgeArmed
                  ? "border-threat-critical bg-threat-critical/20 text-threat-critical"
                  : "border-white/[0.1] bg-white/[0.05] text-slate-400 hover:border-threat-critical/40 hover:text-threat-critical"
              }`}
            >
              <Trash2 size={13} /> {purgeArmed ? "Click again to confirm" : busy === "Purge" ? "Purging…" : "Purge"}
            </button>
          </div>
        </div>
        {db && (
          <p className="mt-2 text-[10.5px] text-slate-600">
            {db.counts.posts.toLocaleString()} posts on record
            {db.oldest_post ? ` · oldest ${new Date(db.oldest_post).toLocaleDateString()}` : ""}
            {db.newest_post ? ` · newest ${new Date(db.newest_post).toLocaleString()}` : ""}
          </p>
        )}
      </GlassCard>

      <ModelsPanel />

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
    </div>
  );
}
