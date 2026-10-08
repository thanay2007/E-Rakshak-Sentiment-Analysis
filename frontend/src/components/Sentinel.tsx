import { Check, Loader2, Mic, MicOff, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { usePostDetail } from "./PostDetailProvider";
import { useLiveAlerts } from "../hooks/useLive";
import { useListener, useSpeaker } from "../hooks/useSpeech";
import { useVoiceSession } from "../hooks/useVoiceSession";
import { parseClientAction } from "../lib/clientActions";
import { safeInternalPath } from "../lib/safeUrl";
import { getToken } from "../services/auth";
import { api, downloadFile } from "../services/api";
import type { AssistantAnswer } from "../services/api";

/**
 * SENTINEL, as one microphone button.
 *
 * There is no panel, no transcript and no typed input: the assistant is spoken
 * to and answers out loud, so the only thing an officer needs on screen is
 * whether it is hearing them. The button is the mute control — on, the
 * microphone stays open until it is switched off, including across answers and
 * pauses; off, nothing is sent from this terminal's microphone at all.
 *
 * Critical alerts are read out regardless. That is deliberately not wired to
 * this button: standing the microphone down is about what the console *hears*,
 * and silencing what it *says* about a critical alert is not something a duty
 * terminal should be able to do by accident.
 *
 * One consequence of dropping the transcript, stated because it is a real
 * trade: answers that carry post wording or a SQL trace used to be shown in
 * full rather than spoken, so an officer read the account's words verbatim
 * instead of hearing a model paraphrase them. Those now only exist in audio —
 * except that "explain this post" opens the post itself, so the words are on
 * screen while the assistant explains them.
 *
 * The one other thing on screen is a change waiting for confirmation. The
 * assistant never changes anything on a single utterance: it reads the change
 * back and this card shows it, and it runs only when the officer says yes on
 * the next turn or clicks Confirm here.
 */
const MIC_KEY = "sentinel.voice.microphone";

export default function Sentinel() {
  const navigate = useNavigate();
  const location = useLocation();
  const liveAlerts = useLiveAlerts();

  const [micOn, setMicOn] = useState(() => localStorage.getItem(MIC_KEY) !== "0");
  const [thinking, setThinking] = useState(false);
  const { openPostId, openId } = usePostDetail();
  const [pending, setPending] = useState<{ id: string; summary: string } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [actionNote, setActionNote] = useState<string | null>(null);

  const { speak, cancel, speaking } = useSpeaker();

  // What the assistant is told about the screen: the page, and the post open
  // in the drawer, so "explain this post" means that one.
  const page = openId ? `${location.pathname}?post=${openId}` : location.pathname;

  // ── effects the assistant's tools asked for ──────────────────────────
  // Validated again here (parseClientAction): only the console's own export
  // routes can be downloaded, and ids must look like ids.
  const applyClientAction = useCallback(
    (raw: unknown) => {
      const action = parseClientAction(raw);
      if (!action) return;
      switch (action.type) {
        case "download":
          downloadFile(action.path, action.filename).catch((e) =>
            setActionNote(`Download failed: ${e instanceof Error ? e.message : String(e)}`)
          );
          break;
        case "open_post":
          openPostId(action.post_id);
          break;
        case "confirm":
          setActionNote(null);
          setPending({ id: action.action_id, summary: action.summary });
          break;
        case "confirm_clear":
          setPending(null);
          break;
      }
    },
    [openPostId]
  );

  // A pending action survives a reload on the server; show it again.
  useEffect(() => {
    api
      .pendingAssistantAction()
      .then((r) => applyClientAction(r.pending))
      .catch(() => undefined);
  }, [applyClientAction]);

  const confirmByHand = async () => {
    if (!pending || confirming) return;
    setConfirming(true);
    try {
      const r = await api.confirmAssistantAction(pending.id);
      setPending(null);
      setActionNote("Done.");
      r.client_actions.forEach(applyClientAction);
      if (r.navigate) navigate(safeInternalPath(r.navigate, "/app"));
    } catch (e) {
      setPending(null);
      setActionNote(e instanceof Error ? e.message : String(e));
    } finally {
      setConfirming(false);
    }
  };

  const cancelByHand = () => {
    if (!pending) return;
    void api.cancelAssistantAction(pending.id).catch(() => undefined);
    setPending(null);
  };

  useEffect(() => {
    if (!actionNote) return;
    const t = window.setTimeout(() => setActionNote(null), 6000);
    return () => window.clearTimeout(t);
  }, [actionNote]);

  // ── ask the backend (the path used while the live channel reconnects) ──
  const ask = useCallback(
    async (query: string) => {
      const trimmed = query.trim();
      if (!trimmed || thinking) return;
      setThinking(true);
      try {
        const answer: AssistantAnswer = await api.ask(trimmed, page);
        void speak(answer.speech);
        if (answer.navigate) navigate(safeInternalPath(answer.navigate, "/app"));
        (answer.client_actions ?? []).forEach(applyClientAction);
      } catch {
        await speak("I couldn't reach the server.");
      } finally {
        setThinking(false);
      }
    },
    [applyClientAction, navigate, page, speak, thinking]
  );

  // ── the live channel ─────────────────────────────────────────────────
  // Always on. `Sentinel` renders inside the authenticated shell, so mounting
  // *is* signing in — the session opens here and reopens itself if it drops.
  const token = getToken() ?? "";
  const voice = useVoiceSession({
    token,
    page,
    enabled: Boolean(token),
    // Replies are always spoken: with no transcript on screen, a muted
    // assistant would be one with no output at all.
    muted: false,
    micMuted: !micOn,
    onNavigate: (path) => navigate(safeInternalPath(path, "/app")),
    onClientAction: applyClientAction,
    speakLocally: speak,
    cancelLocalSpeech: cancel,
  });

  // ── keyless fallback recogniser ──────────────────────────────────────
  // Only when the server negotiated `browser` speech-to-text, meaning this
  // deployment has no recognition key. Otherwise the pipeline owns the
  // microphone and this stays shut: two recognisers on one microphone means
  // every question is asked twice.
  const needsBrowserStt = voice.providers?.stt === "browser";

  // Reached through a ref so the recogniser is created once and not torn down
  // and rebuilt every time the callback identity changes.
  const askSpokenRef = useRef<(text: string) => void>(() => {});

  const {
    listening: browserListening, error: browserError, start, stop, clearError,
  } = useListener({
    onUtterance: (transcript) => askSpokenRef.current(transcript),
    continuous: true,
    paused: speaking || voice.speaking || !needsBrowserStt,
  });

  useEffect(() => {
    if (needsBrowserStt && micOn) start();
    else stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsBrowserStt, micOn]);

  // The channel is preferred when it is up, because a question asked there is
  // spoken back; the HTTP endpoint is what answers while it is reconnecting —
  // without that fallback, everything said during a reconnect is dropped.
  const askSpoken = useCallback(
    (text: string) => {
      if (voice.connected) voice.ask(text);
      else void ask(text);
    },
    [ask, voice]
  );
  askSpokenRef.current = askSpoken;

  const listening =
    micOn && (needsBrowserStt ? browserListening : voice.connected && !voice.speaking);
  const error = voice.error ?? browserError;

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

    const fresh = liveAlerts.filter(
      (a) => !announced.current.has(a.id) && a.severity === "critical"
    );
    if (!fresh.length) return;
    fresh.forEach((a) => announced.current.add(a.id));

    const newest = fresh[0];
    const extra = fresh.length > 1 ? ` And ${fresh.length - 1} more.` : "";
    void speak(
      `Critical alert. ${newest.title}. ` +
      `${newest.location ? `In ${newest.location}. ` : ""}` +
      `Threat score ${Math.round(newest.concern_score)}.${extra}`
    );
  }, [liveAlerts, speak]);

  // Spoken sign-off ends the current turn so the assistant answers immediately
  // instead of waiting out the silence timer. The microphone stays open.
  // "ok"/"okay" are deliberately not here: they punctuate ordinary speech, so
  // treating them as a sign-off cuts officers off mid-sentence.
  useEffect(() => {
    if (voice.interim && /\b(over|stop listening|that'?s all|stand down|go ahead)\b[.!]*$/i.test(voice.interim)) {
      voice.endTurn();
    }
  }, [voice]);

  const toggleMic = () => {
    clearError();
    voice.clearError();
    const next = !micOn;
    setMicOn(next);
    localStorage.setItem(MIC_KEY, next ? "1" : "0");
    if (!next) voice.endTurn();
  };

  const title = !micOn
    ? "Microphone off — click to unmute. Critical alerts are still read out."
    : voice.micBlocked
      ? voice.micBlocked
      : error
        ? error
        : voice.speaking || speaking
          ? "Speaking — talk over me to interrupt"
          : thinking || voice.state === "thinking"
            ? "Checking…"
            : voice.connected || browserListening
              ? "Listening — just talk. Click to mute."
              : "Connecting…";

  return (
    <>
    {(pending || actionNote) && (
      <div
        role="alertdialog"
        aria-label="Assistant action"
        className="fixed bottom-24 right-5 z-40 w-[min(22rem,calc(100vw-2.5rem))] rounded-2xl border border-accent/40 bg-base-900/95 p-3 text-xs text-slate-200 shadow-xl backdrop-blur"
      >
        {pending ? (
          <>
            <div className="text-[10px] font-bold uppercase tracking-widest text-accent">
              Confirm this change?
            </div>
            <p className="mt-1 leading-relaxed">{pending.summary}</p>
            <p className="mt-1 text-[10.5px] text-slate-500">
              Say yes / haan / હા, or use the buttons. Nothing has changed yet.
            </p>
            <div className="mt-2 flex gap-2">
              <button
                onClick={() => void confirmByHand()}
                disabled={confirming}
                className="inline-flex items-center gap-1 rounded-lg border border-accent/50 bg-accent/15 px-3 py-1.5 font-bold text-accent hover:bg-accent hover:text-base-900 disabled:opacity-50"
              >
                {confirming ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                Confirm
              </button>
              <button
                onClick={cancelByHand}
                disabled={confirming}
                className="inline-flex items-center gap-1 rounded-lg border border-white/15 bg-white/[0.05] px-3 py-1.5 text-slate-300 hover:text-white disabled:opacity-50"
              >
                <X size={12} /> Cancel
              </button>
            </div>
          </>
        ) : (
          <p>{actionNote}</p>
        )}
      </div>
    )}
    <button
      onClick={toggleMic}
      aria-label={micOn ? "Mute microphone" : "Unmute microphone"}
      aria-pressed={micOn}
      title={title}
      className={`glow-accent fixed bottom-5 right-5 z-40 grid h-14 w-14 place-items-center rounded-full border transition-all duration-300 ${
        voice.speaking
          ? "border-sky-400/50 bg-sky-500/20 text-sky-300"
          : listening
            ? "border-red-400/50 bg-red-500/20 text-red-300"
            : micOn
              ? "border-accent/50 bg-accent/15 text-accent hover:bg-accent hover:text-base-900"
              : "border-white/15 bg-white/[0.06] text-slate-500 hover:text-slate-300"
      }`}
    >
      {/* The ring tracks the microphone rather than pulsing on a timer: an
          open microphone should look like one, and an officer can see at a
          glance that it is hearing them. */}
      {listening && (
        <span
          className="absolute inset-0 rounded-full border border-red-400/40 transition-transform duration-100"
          style={{ transform: `scale(${1 + Math.min(voice.level * 4, 0.45)})` }}
        />
      )}
      {voice.speaking && (
        <span className="absolute inset-0 animate-ping rounded-full border border-sky-400/40" />
      )}
      {/* A microphone, always — the button's colour and ring say what state it
          is in. The spinner is only for an answer actually being worked out,
          and the session expires that state, so it cannot stick. */}
      {!micOn ? (
        <MicOff size={20} />
      ) : thinking || voice.state === "thinking" ? (
        <Loader2 size={20} className="animate-spin" />
      ) : (
        <Mic size={20} />
      )}
    </button>
    </>
  );
}
