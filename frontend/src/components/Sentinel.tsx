import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle, Ear, Loader2, Mic, MicOff, ShieldCheck, Volume2, VolumeX, X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useLiveAlerts } from "../hooks/useLive";
import { extractCommand, speechSupport, useListener, useSpeaker } from "../hooks/useSpeech";
import { safeInternalPath } from "../lib/safeUrl";
import { api } from "../services/api";
import type { AssistantAnswer, AssistantCapabilities } from "../services/api";

interface Turn {
  id: number;
  role: "officer" | "sentinel";
  text: string;
  intent?: string;
  refused?: boolean;
}

const WAKE_KEY = "sentinel.voice.wake";
const READ_KEY = "sentinel.voice.readAlerts";
const MUTE_KEY = "sentinel.voice.muted";

const flag = (key: string, fallback = false): boolean => {
  const raw = localStorage.getItem(key);
  return raw === null ? fallback : raw === "1";
};

let turnId = 0;

export default function Sentinel() {
  const navigate = useNavigate();
  const location = useLocation();
  const liveAlerts = useLiveAlerts();
  const support = useRef(speechSupport()).current;

  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [thinking, setThinking] = useState(false);
  const [caps, setCaps] = useState<AssistantCapabilities | null>(null);

  // Wake-word mode is off by default and deliberately so: it holds the
  // microphone open, and in Chrome that streams audio to Google's speech
  // service. That is a decision for the officer at the terminal, not a default.
  const [wake, setWake] = useState(() => flag(WAKE_KEY));
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
        });
        await say(answer.speech);
        // Navigation targets only ever come from the backend's deterministic
        // layer — never from the LLM — but they still go through the same
        // in-app path check the sign-in redirect uses. A path from the network
        // is a path from the network.
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

  // ── microphone ───────────────────────────────────────────────────────
  const handleUtterance = useCallback(
    (transcript: string) => {
      if (wake) {
        // In wake-word mode everything is transcribed but only an utterance
        // that names Sentinel is acted on — otherwise the assistant answers
        // half of the room's conversation.
        const command = extractCommand(transcript);
        if (command === null) return;
        if (!command) {
          void say("Yes?");
          return;
        }
        void ask(command);
        return;
      }
      // Push-to-talk: the click was the wake word. Strip it anyway in case the
      // officer said it out of habit.
      void ask(extractCommand(transcript) ?? transcript);
    },
    [ask, say, wake]
  );

  const { listening, interim, error, start, stop, clearError } = useListener({
    onUtterance: handleUtterance,
    continuous: wake,
    paused: speaking,
  });

  // Wake-word mode owns the microphone; push-to-talk opens it per question.
  useEffect(() => {
    if (wake) start();
    else stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wake]);

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

  /** One button, one meaning: open up and start talking; press again to stop.
   *
   *  In wake-word mode the microphone is not this button's to close — killing
   *  the session directly would leave the "Hey Sentinel" toggle showing on
   *  while nothing was listening. Flip the mode instead, and the effect that
   *  owns the microphone follows.
   */
  const toggleMic = () => {
    clearError();
    setOpen(true);
    if (!support.listen) return;
    if (wake) {
      setWake(false);
      persist(WAKE_KEY, false);
      return;
    }
    if (listening) stop();
    else start();
  };

  const busy = thinking || speaking;

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
            aria-label="Sentinel voice assistant"
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
                <div className="text-xs font-bold tracking-wide text-slate-100">SENTINEL</div>
                <div className="text-[10px] text-slate-500">
                  {listening
                    ? wake
                      ? "listening for “Hey Sentinel”"
                      : "listening…"
                    : speaking
                      ? "speaking…"
                      : thinking
                        ? "checking…"
                        : "read-only assistant"}
                </div>
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
                    Ask me about what’s being monitored. I read the live picture
                    and open pages — I can’t change, action or export anything,
                    and I won’t discuss accounts, credentials, the audit trail or
                    biometrics over a microphone.
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {(caps?.examples ?? [
                      "Brief me",
                      "Trends in Surat",
                      "Any critical alerts?",
                      "Highest threat post today",
                    ]).map((example) => (
                      <button
                        key={example}
                        onClick={() => void ask(example)}
                        className="rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[10px] text-slate-400 hover:border-accent/30 hover:text-accent"
                      >
                        {example}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {turns.map((turn) => (
                <div
                  key={turn.id}
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
                  checking the live picture…
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
              <TypedAsk onAsk={ask} disabled={busy} />
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <Toggle
                  on={wake}
                  disabled={!support.listen}
                  onChange={(v) => {
                    setWake(v);
                    persist(WAKE_KEY, v);
                  }}
                  icon={Ear}
                  label="“Hey Sentinel”"
                  title={
                    support.listen
                      ? "Keeps the microphone open. In Chrome, audio is sent to Google’s speech service."
                      : "This browser has no speech recognition."
                  }
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
              {wake && (
                <p className="text-[9px] leading-relaxed text-slate-600">
                  Microphone open. Chrome and Edge process speech in the cloud,
                  not on this machine — turn this off for sensitive briefings.
                </p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* the orb */}
      <button
        onClick={toggleMic}
        aria-label={listening ? "Stop listening" : "Ask Sentinel"}
        title={
          support.listen
            ? "Ask Sentinel — click to talk, click again to stop"
            : "Ask Sentinel (typing only — this browser has no speech recognition)"
        }
        className={`glow-accent fixed bottom-5 right-5 z-40 grid h-14 w-14 place-items-center rounded-full border transition-all duration-300 ${
          listening
            ? "border-red-400/50 bg-red-500/20 text-red-300"
            : "border-accent/50 bg-accent/15 text-accent hover:bg-accent hover:text-base-900"
        }`}
      >
        {listening && (
          <span className="absolute inset-0 animate-ping rounded-full border border-red-400/40" />
        )}
        {thinking ? (
          <Loader2 size={20} className="animate-spin" />
        ) : listening ? (
          <Mic size={20} />
        ) : support.listen ? (
          <ShieldCheck size={20} />
        ) : (
          <MicOff size={20} />
        )}
      </button>
    </>
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
        maxLength={280}
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
  icon: typeof Ear;
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
