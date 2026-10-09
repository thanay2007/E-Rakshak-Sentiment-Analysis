import {
  Activity, AlertTriangle, Database, Download, Settings as SettingsIcon, Trash2, } from "lucide-react";
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
 * Deliberately NOT here: API keys, model internals and the scoring formula.
 * Keys belong in backend/.env — a console that displays them turns every
 * shoulder-surfer and every screenshot into a credential leak, and one that
 * lets you edit them puts secret rotation behind a session cookie. The scoring
 * weights and model architecture are documentation, not settings; they live in
 * the Analysis Stack panel below and in the Intel Guide, where they can be read
 * without implying they are dials to turn.
 */
export default function Settings() {
  const { data: sys, refresh } = usePolling(() => api.systemStatus(), 15000);
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [purgeDays, setPurgeDays] = useState(30);
  const [purgeArmed, setPurgeArmed] = useState(false);

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

  const db = sys?.database;

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
            <div className="text-xs uppercase tracking-widest text-slate-500">Backend</div>
            <div className={`mt-1 font-mono text-sm font-bold ${sys ? "text-threat-neutral" : "text-threat-critical"}`}>
              {sys ? "ONLINE" : "UNREACHABLE"}
            </div>
            <div className="mt-0.5 truncate font-mono text-xs text-slate-600">
              {sys ? `up ${fmtUptime(sys.uptime_seconds)}` : API_BASE}
            </div>
          </div>
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="text-xs uppercase tracking-widest text-slate-500">Collection</div>
            <div
              className={`mt-1 font-mono text-sm font-bold ${
                sys?.scheduler_running ? "text-threat-neutral" : "text-threat-critical"
              }`}
            >
              {sys?.scheduler_running ? "RUNNING" : "STOPPED"}
            </div>
            <div className="mt-0.5 text-xs text-slate-600">
              {sys?.simulation ? "simulated stream" : "live platform APIs"}
              {sys?.scheduler_running ? ` · every ${sys.ingest_interval_seconds}s` : ""}
            </div>
          </div>
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="text-xs uppercase tracking-widest text-slate-500">Analysis</div>
            <div className="mt-1 font-mono text-sm font-bold text-accent">
              {sys?.nlp_mode === "full" ? "3 MODELS" : "LEXICON ONLY"}
            </div>
            <div className="mt-0.5 text-xs text-slate-600">
              {sys?.nlp_mode === "full"
                ? "consensus + LLM final check"
                : "transformer stack unavailable"}
            </div>
          </div>
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="text-xs uppercase tracking-widest text-slate-500">Corpus</div>
            <div className="mt-1 font-mono text-sm font-bold text-slate-200">
              {db ? `${db.counts.posts.toLocaleString()} posts` : "—"}
            </div>
            <div className="mt-0.5 truncate text-xs text-slate-600">
              {db ? `${db.counts.alerts} alerts · ${db.url}` : ""}
            </div>
          </div>
        </div>

        {sys && !sys.scheduler_running && (
          <p className="mt-3 flex items-start gap-2 rounded-xl border border-threat-high/30 bg-threat-high/[0.06] p-2.5 text-[11.5px] text-threat-high">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            The background collector is not running, so no new posts are being collected. Alerts
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
            <span className="text-[13px] text-slate-500">purge posts older than</span>
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
            <span className="text-[13px] text-slate-500">days</span>
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
          <p className="mt-2 text-xs text-slate-600">
            {db.counts.posts.toLocaleString()} posts on record
            {db.oldest_post ? ` · oldest ${new Date(db.oldest_post).toLocaleDateString()}` : ""}
            {db.newest_post ? ` · newest ${new Date(db.newest_post).toLocaleString("en-IN", { hour12: true })}` : ""}
            {" · "}purging is irreversible and is recorded in the audit log.
          </p>
        )}
        {result && <p className="mt-2 text-[11.5px] font-medium text-threat-neutral">{result}</p>}
      </GlassCard>

      
    </div>
  );
}
