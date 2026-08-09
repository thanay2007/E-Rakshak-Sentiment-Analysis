import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle, Database, Loader2, Mic, MicOff, ShieldCheck,
  Volume2, VolumeX, X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useLiveAlerts } from "../hooks/useLive";
import { useListener, useSpeaker } from "../hooks/useSpeech";
import { useVoiceSession } from "../hooks/useVoiceSession";
import { safeInternalPath } from "../lib/safeUrl";
import { getToken } from "../services/auth";
import { api } from "../services/api";
import type {
  AssistantAnswer, AssistantCapabilities, AssistantPostRow, AssistantSqlResult,
  AssistantStep,
} from "../services/api";

interface Turn {
  id: number;
  role: "officer" | "sentinel";
  text: string;
  intent?: string;
  refused?: boolean;
  /** Which lookups produced this answer — shown so the officer can tell a
   *  figure that came from the database from one the model phrased. */
  trace?: AssistantStep[];
  /** Per-tool detail. Rendered on screen rather than spoken: a post's own
   *  words belong in front of the officer, not read aloud by the system. */
  data?: Record<string, unknown>;
}

/** Tool names are an implementation detail; these are what an officer reads. */
const TOOL_LABELS: Record<string, string> = {
  situation_brief: "situation brief",
  count_posts: "post counts",
  breakdown: "breakdown",
  timeseries: "trend over time",
  trending_hashtags: "trending hashtags",
  top_posts: "top posts",
  list_alerts: "alerts",
  city_comparison: "city comparison",
  coordination_check: "coordination check",
  watchlist_status: "watchlist",
  emerging_claims: "emerging claims",
  model_status: "model status",
  explain_project: "documentation",
  run_sql: "database query",
  navigate: "navigation",
};

const READ_KEY = "sentinel.voice.readAlerts";
const MUTE_KEY = "sentinel.voice.muted";
/** The one microphone control there is: stand it down for a sensitive
 *  briefing. Not a wake word and not a mode — the assistant is on by default
 *  and this is how an officer turns it off, not how they turn it on. */
const MIC_KEY = "sentinel.voice.microphone";

const flag = (key: string, fallback = false): boolean => {
  const raw = localStorage.getItem(key);
  return raw === null ? fallback : raw === "1";
};

let turnId = 0;

export default function Sentinel() {
  const navigate = useNavigate();
  const location = useLocation();
  const liveAlerts = useLiveAlerts();

  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [thinking, setThinking] = useState(false);
  const [caps, setCaps] = useState<AssistantCapabilities | null>(null);

  // The assistant listens from sign-in. There is no mode to arm and no wake
  // word to remember: an officer who wants to ask something asks it. The one
  // control is the opposite of the old one — a way to stand the microphone
  // *down*, which persists so a terminal left muted stays muted.
  const [micOn, setMicOn] = useState(() => flag(MIC_KEY, true));
  const [readAlerts, setReadAlerts] = useState(() => flag(READ_KEY, true));
  const [muted, setMuted] = useState(() => flag(MUTE_KEY));

  const { speak, cancel, speaking } = useSpeaker();
  const scrollRef = useRef<HTMLDivElement>(null);

  const say = useCallback(
    async (text: string) => {
      if (muted) return;
      await speak(text);
    },
    [muted, speak]
  );

  const push = useCallback((turn: Omit<Turn, "id">) => {
    turnId += 1;
    setTurns((prev) => [...prev.slice(-19), { ...turn, id: turnId }]);
  }, []);

  // ── ask the backend ──────────────────────────────────────────────────
  const ask = useCallback(
    async (query: string) => {
      const trimmed = query.trim();
      if (!trimmed || thinking) return;
      push({ role: "officer", text: trimmed });
      setThinking(true);
      setOpen(true);
      try {
        const answer: AssistantAnswer = await api.ask(trimmed, location.pathname);
        push({
          role: "sentinel",
          text: answer.reply,
          intent: answer.intent,
          refused: answer.intent === "refused",
          trace: answer.trace,
          data: answer.data,
        });
        void say(answer.speech);
        if (answer.navigate) navigate(safeInternalPath(answer.navigate, "/app"));
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "I couldn't reach the server.";
        push({ role: "sentinel", text: message });
        await say("I couldn't reach the server.");
      } finally {
        setThinking(false);
      }
    },
    [location.pathname, navigate, push, say, thinking]
  );

  // ── the live channel ─────────────────────────────────────────────────
  // Always on. `Sentinel` renders inside the authenticated shell, so mounting
  // *is* signing in — the session opens here and reopens itself if it drops.
  // Its turns are mirrored into the same transcript as the typed path so the
  // panel renders one conversation rather than two.
  const mirrored = useRef(new Set<string>());
  const token = getToken() ?? "";
  const voice = useVoiceSession({
    token,
    page: location.pathname,
    enabled: Boolean(token),
    muted,
    micMuted: !micOn,
    onNavigate: (path) => navigate(safeInternalPath(path, "/app")),
    speakLocally: say,
    cancelLocalSpeech: cancel,
  });

  useEffect(() => {
    voice.turns.forEach((turn) => {
      if (mirrored.current.has(turn.id)) return;
      mirrored.current.add(turn.id);
      push({ role: turn.role, text: turn.text, intent: "live" });
    });
  }, [voice.turns, push]);

  // ── keyless fallback recogniser ──────────────────────────────────────
  // Only when the server negotiated `browser` speech-to-text, meaning this
  // deployment has no recognition key. Otherwise the pipeline owns the
  // microphone and this stays shut: two recognisers on one microphone means
  // every question is asked twice.
  const needsBrowserStt = voice.providers?.stt === "browser";

  const {
    listening: browserListening, interim: browserInterim, error: browserError,
    start, stop, clearError,
  } = useListener({
    onUtterance: (transcript) => voice.ask(transcript),
    continuous: true,
    paused: speaking || voice.speaking || !needsBrowserStt,
  });

  useEffect(() => {
    if (needsBrowserStt && micOn) start();
    else stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsBrowserStt, micOn]);

  const listening =
    micOn && (needsBrowserStt ? browserListening : voice.connected && !voice.speaking);
  const interim = voice.interim || browserInterim;
  const error = voice.error ?? browserError;

  const persist = (key: string, value: boolean) =>
    localStorage.setItem(key, value ? "1" : "0");

  // ── read new critical alerts aloud ───────────────────────────────────
  const announced = useRef<Set<string>>(new Set());
  const primed = useRef(false);

  useEffect(() => {
    // Skip whatever was already on screen when this mounted — an officer
    // opening the dashboard should not be read a backlog.
    if (!primed.current) {
      liveAlerts.forEach((a) => announced.current.add(a.id));
      primed.current = true;
      return;
    }
    if (!readAlerts || muted) return;

    const fresh = liveAlerts.filter(
      (a) => !announced.current.has(a.id) && a.severity === "critical"
    );
    if (!fresh.length) return;
    fresh.forEach((a) => announced.current.add(a.id));

    const newest = fresh[0];
    const extra = fresh.length > 1 ? ` And ${fresh.length - 1} more.` : "";
    const line =
      `Critical alert. ${newest.title}. ` +
      `${newest.location ? `In ${newest.location}. ` : ""}` +
      `Threat score ${Math.round(newest.threat_score)}.${extra}`;
    push({ role: "sentinel", text: line, intent: "alert" });
    void say(line);
  }, [liveAlerts, readAlerts, muted, push, say]);

  useEffect(() => {
    if (open && !caps) api.assistantCapabilities().then(setCaps).catch(() => {});
  }, [open, caps]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, thinking]);

  // 1. Auto-close mic when the agent finishes answering (transitions back to listening or idle).
  // This solves the issue of the mic staying open automatically after responding.
  const previousState = useRef(voice.state);
  useEffect(() => {
    if ((previousState.current === "speaking" || previousState.current === "thinking") && 
        (voice.state === "listening" || voice.state === "idle")) {
      setMicOn(false);
      persist(MIC_KEY, false);
    }
    previousState.current = voice.state;
  }, [voice.state]);

  // 2. Stop words: instantly end the turn when specific words are heard.
  useEffect(() => {
    if (interim && /\b(okay|ok|over|stop listening|that'?s all|stand down)\b[.!]*$/i.test(interim)) {
      voice.endTurn();
      // DO NOT turn off the mic here, or we won't hear the response!
    }
    
    // Fallback for typed turns or final transcriptions.
    const last = turns[turns.length - 1];
    if (last && last.role === "officer" && /\b(okay|ok|over|stop listening|that'?s all|stand down)\b[.!]*$/i.test(last.text)) {
      voice.endTurn();
    }
  }, [interim, turns, voice]);

  // 3. Auto-close mic after 3 seconds of extended pause.
  const lastLoud = useRef(Date.now());
  
  useEffect(() => {
    if (voice.level > 0.03) lastLoud.current = Date.now();
  }, [voice.level]);

  useEffect(() => {
    if (!micOn) return;
    
    // Reset timer when mic is turned on.
    lastLoud.current = Date.now();
    
    const interval = setInterval(() => {
      // Don't timeout if it's currently speaking or thinking
      if (voice.speaking || thinking || voice.state === "thinking" || voice.state === "speaking") {
        lastLoud.current = Date.now();
        return;
      }
      
      if (Date.now() - lastLoud.current > 3000) {
        setMicOn(false);
        persist(MIC_KEY, false);
        voice.endTurn();
      }
    }, 500);
    
    return () => clearInterval(interval);
  }, [micOn, voice.speaking, thinking, voice.state, voice]);

  /** The orb. The microphone is already open, so this cannot mean "start
   *  listening" — it means the two things an officer actually wants mid-answer:
   *  stop talking, or show me the transcript. If the mic is off, it turns it on. */
  const orbClick = () => {
    clearError();
    voice.clearError();
    if (voice.speaking) {
      voice.interrupt();
      return;
    }
    if (!micOn) {
      setMicOn(true);
      persist(MIC_KEY, true);
      setOpen(true);
    } else {
      setOpen((current) => !current);
    }
  };

  // One entry point for a typed question, so the input does not have to know
  // which transport is carrying it. The channel is preferred when it is up,
  // because a question asked there is spoken back; the HTTP endpoint is what
  // answers while it is reconnecting.
  const submit = useCallback(
    (text: string) => {
      setOpen(true);
      if (voice.connected) voice.ask(text);
      else void ask(text);
    },
    [ask, voice]
  );

  const busy = thinking || speaking || voice.state === "thinking";

  /** One line describing what the assistant is doing, in the officer's terms
   *  rather than the pipeline's. "Standing by" and not "connected", because
   *  the interesting question is whether it is listening. */
  const status = !micOn
    ? "microphone off"
    : voice.micBlocked
      ? "microphone blocked — typing still works"
      : voice.needsGesture
        ? "click anywhere to enable audio"
        : voice.speaking || speaking
          ? "speaking — talk over me to interrupt"
          : busy
            ? "checking…"
            : voice.connected
              // The microphone being open is not the same as the console
              // being addressed. An officer who is not told the difference
              // reads a filtered utterance as a broken microphone — so the
              // line says which of the two states it is actually in.
              ? voice.wake.required && !voice.wake.listening
                ? "say “E-Rakshak” or “Sentinel” to ask"
                : `listening${voice.providers?.stt ? ` · ${voice.providers.stt}` : ""}`
              : needsBrowserStt && browserListening
                ? "listening"
                : "connecting…";

  return (
    <>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.97 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="fixed bottom-24 right-5 z-40 flex max-h-[70vh] w-[min(400px,calc(100vw-2.5rem))] flex-col overflow-hidden rounded-2xl border border-white/[0.08] bg-base-900/95 backdrop-blur-xl"
            role="dialog"
            aria-label="E-Rakshak voice assistant"
          >
            {/* header */}
            <div className="flex items-center gap-2.5 border-b border-white/[0.06] px-4 py-3">
              <span className="relative grid h-8 w-8 place-items-center rounded-full border border-accent/40 bg-accent/15">
                <ShieldCheck size={15} className="text-accent" />
                {listening && (
                  <span className="absolute -inset-1 animate-ping rounded-full border border-accent/40" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-bold tracking-wide text-slate-100">E-RAKSHAK</div>
                <div className="text-[10px] text-slate-500">{status}</div>
              </div>

              <button
                onClick={() => {
                  const next = !muted;
                  setMuted(next);
                  persist(MUTE_KEY, next);
                  if (next) cancel();
                }}
                title={muted ? "Unmute spoken replies" : "Mute spoken replies"}
                className="rounded-lg p-1.5 text-slate-500 hover:bg-white/[0.06] hover:text-slate-300"
              >
                {muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
              </button>
              <button
                onClick={() => {
                  setOpen(false);
                  cancel();
                }}
                title="Close"
                className="rounded-lg p-1.5 text-slate-500 hover:bg-white/[0.06] hover:text-slate-300"
              >
                <X size={14} />
              </button>
            </div>

            {/* transcript */}
            <div ref={scrollRef} className="flex-1 space-y-2.5 overflow-y-auto px-4 py-3">
              {turns.length === 0 && (
                <div className="space-y-3">
                  <p className="text-[11px] leading-relaxed text-slate-500">
                    Ask me anything about what’s being monitored, or about how
                    E-RAKSHAK itself works. I query the live data
                    {caps?.sql_enabled ? " directly" : ""} and answer from the
                    product’s own documentation — I can’t change, action or
                    export anything, and I won’t discuss accounts, credentials,
                    the audit trail or biometrics over a microphone.
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {(caps?.examples ?? [
                      "Brief me",
                      "How is the threat score calculated?",
                      "Which city is worst this week?",
                      "Any critical alerts?",
                    ]).map((example) => (
                      <button
                        key={example}
                        onClick={() => submit(example)}
                        className="rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[10px] text-slate-400 hover:border-accent/30 hover:text-accent"
                      >
                        {example}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {turns.map((turn) => (
                <div key={turn.id} className="space-y-1.5">
                  <div
                    className={turn.role === "officer" ? "flex justify-end" : "flex justify-start"}
                  >
                    <div
                      className={`max-w-[85%] rounded-xl px-3 py-2 text-[11px] leading-relaxed ${
                        turn.role === "officer"
                          ? "border border-white/[0.08] bg-white/[0.05] text-slate-300"
                          : turn.refused
                            ? "border border-amber-500/25 bg-amber-500/10 text-amber-200"
                            : turn.intent === "alert"
                              ? "border border-red-500/25 bg-red-500/10 text-red-200"
                              : "border border-accent/20 bg-accent/[0.07] text-slate-200"
                      }`}
                    >
                      {turn.text}
                    </div>
                  </div>
                  {turn.role === "sentinel" && <Working trace={turn.trace} />}
                  {turn.role === "sentinel" && <Evidence data={turn.data} />}
                </div>
              ))}

              {interim && (
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-xl border border-dashed border-white/[0.1] px-3 py-2 text-[11px] italic text-slate-500">
                    {interim}
                  </div>
                </div>
              )}

              {thinking && (
                <div className="flex items-center gap-2 text-[11px] text-slate-500">
                  <Loader2 size={12} className="animate-spin" />
                  querying the live picture…
                </div>
              )}

              {error && (
                <p className="flex items-start gap-2 rounded-xl border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-[10px] text-amber-300">
                  <AlertTriangle size={12} className="mt-px shrink-0" />
                  <span>{error}</span>
                </p>
              )}
            </div>

            {/* controls */}
            <div className="space-y-2.5 border-t border-white/[0.06] px-4 py-3">
              <TypedAsk onAsk={submit} disabled={busy} />
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <Toggle
                  on={micOn}
                  onChange={(v) => {
                    setMicOn(v);
                    persist(MIC_KEY, v);
                    if (!v) cancel();
                  }}
                  icon={micOn ? Mic : MicOff}
                  label="Microphone"
                  title="Sentinel listens from sign-in but only answers when addressed by name. Turn this off to stand the microphone down for a sensitive briefing — it stays off on this terminal until turned back on."
                />
                <Toggle
                  on={readAlerts}
                  onChange={(v) => {
                    setReadAlerts(v);
                    persist(READ_KEY, v);
                  }}
                  icon={Volume2}
                  label="Read critical alerts"
                  title="Speak new critical alerts as they arrive."
                />
              </div>
              <p className="text-[9px] leading-relaxed text-slate-600">
                {micOn
                  ? voice.micBlocked
                    ? voice.micBlocked
                    : needsBrowserStt
                    ? "Listening. This deployment has no recognition key, so speech is transcribed by the browser — Chrome and Edge do that in the cloud, not on this machine."
                    : voice.wake.required
                    ? "Say “Sentinel” and then your question — follow-ups need no name for a few seconds after an answer, so the rest of the room's conversation is ignored. Speech is recognised on the SENTINEL server and never sent to a browser vendor. Talk over an answer to interrupt it."
                    : "Listening. Speech is recognised on the SENTINEL server and never sent to a browser vendor. Talk over an answer to interrupt it."
                  : "The microphone is off. Typed questions still work."}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* the orb — it reports, it does not arm. The microphone is already on. */}
      <button
        onClick={orbClick}
        aria-label={
          voice.speaking ? "Stop Sentinel speaking" : open ? "Hide Sentinel" : "Show Sentinel"
        }
        title={
          voice.speaking
            ? "Speaking — click to stop, or just talk over it"
            : micOn
              ? "Sentinel is listening. Click to show the transcript."
              : "Microphone off — click to open and turn it back on"
        }
        className={`glow-accent fixed bottom-5 right-5 z-40 grid h-14 w-14 place-items-center rounded-full border transition-all duration-300 ${
          voice.speaking
            ? "border-sky-400/50 bg-sky-500/20 text-sky-300"
            : listening
              ? "border-red-400/50 bg-red-500/20 text-red-300"
              : "border-accent/50 bg-accent/15 text-accent hover:bg-accent hover:text-base-900"
        }`}
      >
        {/* The ring tracks the microphone rather than pulsing on a timer: an
            always-open microphone should look like one, and an officer can see
            at a glance that it is hearing them. */}
        {listening && (
          <span
            className="absolute inset-0 rounded-full border border-red-400/40 transition-transform duration-100"
            style={{ transform: `scale(${1 + Math.min(voice.level * 4, 0.45)})` }}
          />
        )}
        {voice.speaking && (
          <span className="absolute inset-0 animate-ping rounded-full border border-sky-400/40" />
        )}
        {thinking || voice.state === "thinking" ? (
          <Loader2 size={20} className="animate-spin" />
        ) : !micOn ? (
          <MicOff size={20} />
        ) : listening ? (
          <Mic size={20} />
        ) : (
          <ShieldCheck size={20} />
        )}
      </button>
    </>
  );
}

/** What the assistant looked at, in the order it looked.
 *
 *  Present for a reason beyond decoration: it is how an officer distinguishes
 *  a number that came out of the database from a sentence the model phrased.
 *  An answer with no chips beneath it was not grounded in a lookup, and should
 *  be read as such.
 */
function Working({ trace }: { trace?: AssistantStep[] }) {
  if (!trace?.length) return null;
  const seen = new Set<string>();
  const unique = trace.filter((s) => !seen.has(s.tool) && seen.add(s.tool));
  return (
    <div className="flex flex-wrap items-center gap-1 pl-0.5">
      <span className="text-[9px] uppercase tracking-wide text-slate-600">checked</span>
      {unique.map((step) => (
        <span
          key={step.tool}
          title={JSON.stringify(step.arguments)}
          className="rounded-md border border-white/[0.07] bg-white/[0.03] px-1.5 py-0.5 text-[9px] text-slate-500"
        >
          {TOOL_LABELS[step.tool] ?? step.tool}
        </span>
      ))}
    </div>
  );
}

/** The detail behind an answer, shown but never spoken.
 *
 *  Two things land here. Post wording, because it is written by the accounts
 *  under investigation and belongs in front of an officer verbatim rather than
 *  paraphrased into audio by a model. And the SQL the assistant ran, because a
 *  figure an officer may act on should be traceable to the query that produced
 *  it without opening the audit trail.
 */
function Evidence({ data }: { data?: Record<string, unknown> }) {
  if (!data) return null;
  const posts = (data.top_posts as { posts?: AssistantPostRow[] } | undefined)?.posts;
  const sql = data.run_sql as AssistantSqlResult | undefined;
  if (!posts?.length && !sql?.columns?.length) return null;

  return (
    <div className="space-y-1.5 pl-0.5">
      {posts?.slice(0, 3).map((post) => (
        <div
          key={post.post_id}
          className="rounded-lg border border-white/[0.07] bg-white/[0.02] px-2.5 py-2"
        >
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[9px] text-slate-500">
            <span className="font-semibold text-slate-400">{post.platform}</span>
            <span>{post.author_handle}</span>
            {post.location && <span>· {post.location}</span>}
            <span
              className={`ml-auto rounded px-1 py-px font-semibold ${
                post.threat_score >= 74
                  ? "bg-red-500/15 text-red-300"
                  : post.threat_score >= 65
                    ? "bg-amber-500/15 text-amber-300"
                    : "bg-white/[0.06] text-slate-400"
              }`}
            >
              {Math.round(post.threat_score)} · {post.threat_label}
            </span>
          </div>
          {post.text_excerpt && (
            <p className="mt-1 text-[10px] leading-relaxed text-slate-400">
              {post.text_excerpt}
            </p>
          )}
        </div>
      ))}

      {sql?.columns?.length ? (
        <details className="rounded-lg border border-white/[0.07] bg-white/[0.02]">
          <summary className="flex cursor-pointer items-center gap-1.5 px-2.5 py-1.5 text-[9px] text-slate-500 hover:text-slate-300">
            <Database size={10} />
            {sql.rows.length} row{sql.rows.length === 1 ? "" : "s"} from a read-only
            query · {sql.elapsed_ms}ms
          </summary>
          <div className="max-h-40 overflow-auto border-t border-white/[0.05] px-2.5 py-2">
            <table className="w-full text-left text-[9px]">
              <thead>
                <tr className="text-slate-600">
                  {sql.columns.map((column) => (
                    <th key={column} className="pr-3 pb-1 font-semibold">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="text-slate-400">
                {sql.rows.slice(0, 20).map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j} className="pr-3 py-px">
                        {cell === null ? "—" : String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <pre className="mt-2 whitespace-pre-wrap break-words border-t border-white/[0.05] pt-2 text-[8px] leading-relaxed text-slate-600">
              {sql.sql}
            </pre>
          </div>
        </details>
      ) : null}
    </div>
  );
}

function TypedAsk({
  onAsk,
  disabled,
}: {
  onAsk: (q: string) => void | Promise<void>;
  disabled: boolean;
}) {
  const [value, setValue] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!value.trim()) return;
        void onAsk(value);
        setValue("");
      }}
      className="flex gap-2"
    >
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        maxLength={600}
        placeholder="or type a question…"
        aria-label="Ask Sentinel"
        className="w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-[11px] text-slate-100 placeholder-slate-600 outline-none focus:border-accent/50"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="rounded-xl border border-accent/40 bg-accent/10 px-3 text-[11px] font-semibold text-accent disabled:opacity-40"
      >
        Ask
      </button>
    </form>
  );
}

function Toggle({
  on,
  onChange,
  icon: Icon,
  label,
  title,
  disabled = false,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
  icon: typeof Mic;
  label: string;
  title: string;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={() => onChange(!on)}
      disabled={disabled}
      title={title}
      aria-pressed={on}
      className={`flex items-center gap-1.5 text-[10px] transition-colors disabled:opacity-40 ${
        on ? "text-accent" : "text-slate-500 hover:text-slate-300"
      }`}
    >
      <span
        className={`grid h-4 w-7 place-items-center rounded-full border px-0.5 transition-colors ${
          on ? "border-accent/50 bg-accent/20" : "border-white/[0.12] bg-white/[0.04]"
        }`}
      >
        <span
          className={`h-2.5 w-2.5 rounded-full transition-transform ${
            on ? "translate-x-1.5 bg-accent" : "-translate-x-1.5 bg-slate-600"
          }`}
        />
      </span>
      <Icon size={11} />
      {label}
    </button>
  );
}
