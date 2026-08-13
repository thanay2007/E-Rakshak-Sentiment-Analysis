import {
  Activity, AlertTriangle, Bot, Database, Download, Languages,
  RefreshCcw, Settings as SettingsIcon, Trash2, Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import GlassCard, { SectionTitle } from "../components/GlassCard";
import { usePolling } from "../hooks/usePolling";
import { api, API_BASE } from "../services/api";

function fmtUptime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/**
 * Operations console.
 *
 * Scoped to what an analyst or duty supervisor can actually act on from a
 * browser: is collection running, is the analysis stack healthy, are the
 * evidence sources answering, and the maintenance actions on the corpus.
 *
 * Deliberately NOT here: API keys, model internals, the scoring formula and
 * the per-source news quota tables. Keys belong in backend/.env — a console
 * that displays them turns every shoulder-surfer and every screenshot into a
 * credential leak. Model architecture, training data and score weights are
 * documentation rather than settings; they live in the Intel Guide, where they
 * read as reference instead of implying they are dials to turn. What is left on
 * this page is only what a duty supervisor can decide or act on.
 */
export default function Settings() {
  const { data: sys, refresh } = usePolling(() => api.systemStatus(), 15000);
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [purgeDays, setPurgeDays] = useState(30);
  const [purgeArmed, setPurgeArmed] = useState(false);
  const [retrain, setRetrain] = useState<string | null>(null);
  const retrainTimer = useRef<number | null>(null);
  const { data: reanalyse, refresh: refreshReanalyse } = usePolling(
    () => api.reanalyseStatus(),
    10000
  );

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
          setRetrain(
            s.state === "done"
              ? `done in ${s.elapsed_seconds}s — model reloaded`
              : `failed (exit ${s.exit_code})`
          );
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

  const db = sys?.database;
  const llmModels = sys?.llm?.models ?? [];
  const newsSources = sys?.news?.sources ?? [];
  const llmDown = sys?.llm?.enabled && llmModels.length > 0
    && llmModels.every((m) => m.state === "cooling_down");

  return (
    <div className="max-w-4xl space-y-4">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-bold text-slate-200">
          <SettingsIcon size={18} className="text-accent" /> System
        </h1>
        <p className="text-xs text-slate-500">
          operations console · collection health, analysis stack, evidence sources and corpus maintenance
        </p>
      </div>

      {/* ── collection health ─────────────────────────────────────────── */}
      <GlassCard className="p-4">
        <SectionTitle
          title="Collection & Analysis"
          sub="is the console actually watching anything right now"
          right={<Activity size={15} className="text-slate-600" />}
        />
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
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Collection</div>
            <div
              className={`mt-1 font-mono text-sm font-bold ${
                sys?.scheduler_running ? "text-threat-neutral" : "text-threat-critical"
              }`}
            >
              {sys?.scheduler_running ? "RUNNING" : "STOPPED"}
            </div>
            <div className="mt-0.5 text-[10px] text-slate-600">
              {sys?.simulation ? "simulated stream" : "live platform APIs"}
              {sys?.scheduler_running ? ` · every ${sys.ingest_interval_seconds}s` : ""}
            </div>
          </div>
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Analysis</div>
            <div className="mt-1 font-mono text-sm font-bold text-accent">
              {sys?.nlp_mode === "full" ? "3 MODELS" : "LEXICON ONLY"}
            </div>
            <div className="mt-0.5 text-[10px] text-slate-600">
              {sys?.nlp_mode === "full"
                ? "consensus + LLM final check"
                : "transformer stack unavailable"}
            </div>
          </div>
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Corpus</div>
            <div className="mt-1 font-mono text-sm font-bold text-slate-200">
              {db ? `${db.counts.posts.toLocaleString()} posts` : "—"}
            </div>
            <div className="mt-0.5 truncate text-[10px] text-slate-600">
              {db ? `${db.counts.alerts} alerts · ${db.url}` : ""}
            </div>
          </div>
        </div>

        {sys && !sys.scheduler_running && (
          <p className="mt-3 flex items-start gap-2 rounded-xl border border-threat-high/30 bg-threat-high/[0.06] p-2.5 text-[11.5px] text-threat-high">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            The background collector is not running, so nothing new is being ingested. Alerts
            you see are historical. Restart the backend, or use “Collect now” below for a
            one-off pass.
          </p>
        )}
        {sys?.nlp_mode !== "full" && sys && (
          <p className="mt-2 flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/[0.06] p-2.5 text-[11.5px] text-amber-300">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            Only the lexicon model is active — the two trained models are not loaded, so posts
            are being tagged by rules alone and confidence will read lower than usual.
          </p>
        )}
      </GlassCard>

      {/* ── external services ─────────────────────────────────────────────
          One strip, not two panels of reference text. The only operational
          question here is "is anything I depend on unavailable right now" —
          which model answered, and each index's per-day quota table, are not
          decisions a supervisor makes from this screen. */}
      <GlassCard className="p-4">
        <SectionTitle
          title="External Services"
          sub="what is reachable right now — keys are read from backend/.env and never shown here"
          right={<Bot size={15} className="text-slate-600" />}
        />

        {llmDown && (
          <p className="mb-2 flex items-start gap-2 rounded-xl border border-threat-high/30 bg-threat-high/[0.06] p-2.5 text-[11.5px] text-threat-high">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            The LLM is rate-limited. Tagging continues on the three local models; the final check,
            translation and dossiers resume when quota returns.
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-2 rounded-xl bg-white/[0.04] px-3 py-1.5 text-xs">
            <span className={`h-2 w-2 rounded-full ${
              !sys?.llm?.enabled ? "bg-slate-600" : llmDown ? "bg-threat-critical" : "bg-threat-neutral"
            }`} />
            <span className="text-slate-200">LLM final check</span>
            <span className="font-mono text-[10.5px] text-slate-500">
              {!sys?.llm?.enabled ? "not configured" : llmDown ? "rate-limited" : "ready"}
            </span>
          </span>

          {newsSources.map((s) => {
            const used = s.used_today ?? 0;
            const budget = s.daily_budget ?? 0;
            const spent = budget > 0 && used >= budget;
            return (
              <span key={s.name}
                className="inline-flex items-center gap-2 rounded-xl bg-white/[0.04] px-3 py-1.5 text-xs">
                <span className={`h-2 w-2 rounded-full ${
                  !s.configured ? "bg-slate-600" : spent ? "bg-threat-high" : "bg-threat-neutral"
                }`} />
                <span className="text-slate-200">{s.name}</span>
                <span className="font-mono text-[10.5px] text-slate-500">
                  {!s.configured ? "no key" : budget ? `${used}/${budget} today` : "unmetered"}
                </span>
              </span>
            );
          })}
        </div>

        <button
          onClick={() =>
            run("LLM test", async () => {
              const r = await api.testLlm();
              return r.ok
                ? `LLM online — ${r.model} answered in ${r.latency_ms}ms`
                : `LLM unavailable: ${r.error}`;
            })
          }
          disabled={busy !== null}
          className="mt-3 inline-flex items-center gap-1.5 rounded-xl border border-accent/50 bg-accent/15 px-3.5 py-2 text-xs font-bold text-accent hover:bg-accent hover:text-base-900 disabled:opacity-50"
        >
          <Zap size={13} /> {busy === "LLM test" ? "Testing…" : "Test connection"}
        </button>
      </GlassCard>

      {/* ── maintenance ───────────────────────────────────────────────── */}
      <GlassCard className="p-4">
        <SectionTitle
          title="Maintenance"
          sub="actions that run against the live corpus"
          right={<RefreshCcw size={15} className="text-slate-600" />}
        />
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() =>
              run("Collect", async () => {
                const r = await api.crawlNow();
                return `Collection pass complete — ${r.new_posts} new posts ingested`;
              })
            }
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.1] bg-white/[0.05] px-3.5 py-2 text-xs font-semibold text-slate-200 hover:border-accent/40 hover:text-accent disabled:opacity-50"
          >
            <RefreshCcw size={13} /> {busy === "Collect" ? "Collecting…" : "Collect now"}
          </button>
          <button
            onClick={() =>
              run("Translate", async () => {
                const r = await api.translateMissing(60);
                return `Translated ${r.translated} posts — ${r.remaining_candidates} still untranslated`;
              })
            }
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.1] bg-white/[0.05] px-3.5 py-2 text-xs font-semibold text-slate-200 hover:border-accent/40 hover:text-accent disabled:opacity-50"
          >
            <Languages size={13} />
            {busy === "Translate"
              ? "Translating…"
              : `Backfill translations${db ? ` (${db.untranslated_posts})` : ""}`}
          </button>
          <button
            onClick={() =>
              run("Relabel", async () => {
                const r = await api.relabelLanguages();
                return `Language re-detection: ${r.relabeled} posts relabeled`;
              })
            }
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
            <Bot size={13} /> Retrain classical model
          </button>
          <button
            onClick={() =>
              run("Re-analyse", async () => {
                await api.reanalysePosts();
                refreshReanalyse();
                return "Re-analysis started — progress is shown below and survives a page reload.";
              })
            }
            disabled={busy !== null || reanalyse?.state === "running" || reanalyse?.remaining === 0}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.1] bg-white/[0.05] px-3.5 py-2 text-xs font-semibold text-slate-200 hover:border-accent/40 hover:text-accent disabled:opacity-50"
          >
            <Activity size={13} />
            {reanalyse?.state === "running"
              ? "Re-analysing…"
              : reanalyse?.remaining === 0
                ? "Corpus up to date"
                : "Re-analyse stored posts"}
          </button>
        </div>

        {/* Re-analysis progress. Read from the database, not the process, so it
            still reports correctly after a restart mid-run. */}
        {reanalyse && reanalyse.total > 0 && reanalyse.remaining > 0 && (
          <div className="mt-3 rounded-xl border border-amber-500/25 bg-amber-500/[0.05] p-2.5">
            <div className="flex items-center justify-between text-[11.5px]">
              <span className="font-semibold text-amber-300">
                {reanalyse.remaining.toLocaleString()} posts still carry a verdict from the
                previous scoring model
              </span>
              <span className="font-mono text-[10.5px] text-amber-200/80">
                {reanalyse.done.toLocaleString()} / {reanalyse.total.toLocaleString()}
              </span>
            </div>
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/[0.06]">
              <div
                className="h-full rounded-full bg-amber-400/80 transition-all duration-700"
                style={{ width: `${(reanalyse.done / reanalyse.total) * 100}%` }}
              />
            </div>
            <p className="mt-1.5 text-[10.5px] leading-relaxed text-slate-500">
              Their scores came from the retired formula and they have no evidence trail, so
              charts mixing them with newer posts are comparing two scales. Re-analysis replays
              them through the current models; translations and stored news results are kept,
              and no alerts are re-raised.
            </p>
          </div>
        )}
        {db && db.untranslated_posts > 0 && (
          <p className="mt-2 text-[10.5px] text-slate-600">
            {db.untranslated_posts.toLocaleString()} non-English posts have no English gloss on
            record. An analyst who does not read the original judges the translation, so these
            are effectively unreviewable until backfilled.
          </p>
        )}
        {retrain && <p className="mt-2 font-mono text-[11px] text-accent">retrain: {retrain}</p>}
        {result && <p className="mt-2 text-[11.5px] font-medium text-threat-neutral">{result}</p>}
      </GlassCard>

      {/* ── records ───────────────────────────────────────────────────── */}
      <GlassCard className="p-4">
        <SectionTitle
          title="Records & Retention"
          sub="export for the case file · retention purge"
          right={<Database size={15} className="text-slate-600" />}
        />
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
              onChange={(e) => {
                setPurgeDays(Number(e.target.value));
                setPurgeArmed(false);
              }}
              className="w-16 rounded-lg border border-white/[0.08] bg-white/[0.04] px-2 py-1.5 text-center font-mono text-xs text-slate-200 focus:border-accent/40 focus:outline-none"
            />
            <span className="text-[11px] text-slate-500">days</span>
            <button
              onClick={() => {
                if (!purgeArmed) {
                  setPurgeArmed(true);
                  return;
                }
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
              <Trash2 size={13} />{" "}
              {purgeArmed ? "Click again to confirm" : busy === "Purge" ? "Purging…" : "Purge"}
            </button>
          </div>
        </div>
        {db && (
          <p className="mt-2 text-[10.5px] text-slate-600">
            {db.counts.posts.toLocaleString()} posts on record
            {db.oldest_post ? ` · oldest ${new Date(db.oldest_post).toLocaleDateString()}` : ""}
            {db.newest_post ? ` · newest ${new Date(db.newest_post).toLocaleString()}` : ""}
            {" · "}purging is irreversible and is recorded in the audit log.
          </p>
        )}
      </GlassCard>

    </div>
  );
}
