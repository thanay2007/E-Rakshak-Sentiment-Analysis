/** Web Speech API wrappers for the Sentinel assistant.
 *
 *  Two halves, and they are used in quite different circumstances.
 *
 *  **`useSpeaker` is the assistant's voice** whenever no server-side
 *  synthesiser is configured. Which voice it finds is the difference between
 *  an assistant that sounds like a product and one that sounds like a 2013
 *  screen reader, so `pickVoice` ranks rather than takes the first match.
 *
 *  **`useListener` is a fallback recogniser**, used only when the server
 *  negotiated `browser` speech-to-text — that is, when the deployment has no
 *  recognition key at all. Normally the microphone belongs to the live
 *  pipeline in `useVoiceSession` and this stays closed; running both is two
 *  recognisers on one microphone, and every question gets asked twice.
 *
 *  Two things in here are not obvious and both are load-bearing:
 *
 *  1. **The assistant must not hear itself.** Speech synthesis comes out of the
 *     same speakers the microphone is pointed at, so a listener left running
 *     while Sentinel talks transcribes its own answer and asks itself a
 *     question. `useListener` takes a `paused` flag that the component holds
 *     high for the whole duration of an utterance.
 *
 *  2. **Continuous recognition is not continuous.** Chrome ends a session after
 *     a stretch of silence and fires `onend` with no error, so it has to be
 *     restarted — but only when it was not stopped deliberately, or turning the
 *     microphone off would immediately turn it back on.
 *
 *  Privacy, stated plainly because this ships to a police deployment: in
 *  Chrome and Edge the recognition API streams audio to the browser vendor's
 *  speech service. It is not local, which is a further reason it is only the
 *  keyless fallback.
 */
import { useCallback, useEffect, useRef, useState } from "react";

// ── minimal typings ────────────────────────────────────────────────────
// The DOM lib does not ship these consistently across TS versions, and the
// vendor-prefixed constructor is not in it at all.

interface SrAlternative {
  transcript: string;
  confidence: number;
}
interface SrResult {
  isFinal: boolean;
  length: number;
  [index: number]: SrAlternative;
}
interface SrResultList {
  length: number;
  [index: number]: SrResult;
}
interface SrEvent extends Event {
  resultIndex: number;
  results: SrResultList;
}
interface SrErrorEvent extends Event {
  error: string;
  message: string;
}
interface SrInstance extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: SrEvent) => void) | null;
  onerror: ((e: SrErrorEvent) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
}
type SrConstructor = new () => SrInstance;

function recognitionCtor(): SrConstructor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SrConstructor;
    webkitSpeechRecognition?: SrConstructor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function speechSupport(): { listen: boolean; speak: boolean } {
  return {
    listen: recognitionCtor() !== null,
    speak: typeof window !== "undefined" && "speechSynthesis" in window,
  };
}

// ── speaking ───────────────────────────────────────────────────────────

/** Choosing the voice, in the order the qualities actually matter.
 *
 *  The installed set is wildly uneven — Edge on Windows exposes Microsoft's
 *  neural voices, which are the same engine a paid speech API sells; Chrome on
 *  the same machine exposes local SAPI voices from 2013 plus a few of Google's
 *  network ones. Taking `voices[0]`, or the first thing tagged en-IN, is how
 *  you end up with Microsoft David reading threat assessments.
 *
 *  So rank rather than filter, and rank on three things in this order:
 *
 *  1. **Neural.** "Natural"/"Online" in the name marks Microsoft's neural
 *     voices; Google's network voices are the next tier. The gap between a
 *     neural voice and a concatenative one is not subtle.
 *  2. **Female**, because that is what this deployment asked for, and named
 *     explicitly since the API exposes no gender field — only a name.
 *  3. **Indian or British English**, because the content is Gujarati place
 *     names and handles: en-IN says "Vadodara" and "Rajkot" correctly, en-US
 *     does not.
 */
const NEURAL_MARKERS = /natural|online|neural/i;
const GOOGLE_NETWORK = /^google/i;
const FEMALE_NAMES =
  /aria|ava|emma|jenny|michelle|sonia|libby|maisie|neerja|kavya|ananya|swara|zira|heera|female|samantha|karen|moira|tessa|fiona|serena|allison|susan|nicky|joanna|salli|kimberly/i;
const MALE_NAMES = /david|mark|guy|andrew|brian|christopher|eric|roger|steffan|ryan|thomas|george|prabhat|madhur|daniel|alex|fred|male/i;

function scoreVoice(voice: SpeechSynthesisVoice): number {
  let score = 0;
  const name = voice.name;

  if (NEURAL_MARKERS.test(name)) score += 100;
  else if (GOOGLE_NETWORK.test(name)) score += 60;

  if (FEMALE_NAMES.test(name)) score += 40;
  if (MALE_NAMES.test(name)) score -= 60;

  if (/en[-_]IN/i.test(voice.lang)) score += 20;
  else if (/en[-_]GB/i.test(voice.lang)) score += 12;
  else if (/en[-_]AU/i.test(voice.lang)) score += 8;
  else if (/^en/i.test(voice.lang)) score += 6;
  else score -= 40;                 // a non-English voice reading English is unusable

  // A tie between an equal local and remote voice goes to the local one: it
  // starts instantly and the text never leaves the machine.
  if (voice.localService) score += 2;
  return score;
}

function pickVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  if (!voices.length) return null;
  return voices
    .slice()
    .sort((a, b) => scoreVoice(b) - scoreVoice(a))[0] ?? null;
}

export function useSpeaker() {
  const [speaking, setSpeaking] = useState(false);
  const voiceRef = useRef<SpeechSynthesisVoice | null>(null);
  /** Utterances started and not yet finished. A reply arrives as a stream of
   *  sentences, so several are in flight at once and "am I still speaking" is
   *  a count, not a flag — the microphone gate downstream depends on getting
   *  this exactly right. */
  const outstanding = useRef(0);
  /** Bumped by `cancel`, so an utterance that ends after being cancelled
   *  cannot resolve into the state of the reply that replaced it. */
  const generation = useRef(0);

  useEffect(() => {
    if (!("speechSynthesis" in window)) return;
    const load = () => {
      voiceRef.current = pickVoice(window.speechSynthesis.getVoices());
    };
    load();
    // Voices load asynchronously in Chrome; the first getVoices() is often [].
    window.speechSynthesis.addEventListener("voiceschanged", load);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", load);
  }, []);

  const cancel = useCallback(() => {
    if (!("speechSynthesis" in window)) return;
    generation.current += 1;
    outstanding.current = 0;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  const speak = useCallback(
    (text: string) =>
      new Promise<void>((resolve) => {
        if (!("speechSynthesis" in window) || !text.trim()) {
          resolve();
          return;
        }
        // Queued, not cancelled. A reply is delivered a sentence at a time as
        // the model produces it, and cancelling on each one would leave the
        // officer hearing only the last sentence of every answer.
        const mine = generation.current;

        const utterance = new SpeechSynthesisUtterance(text);
        if (voiceRef.current) utterance.voice = voiceRef.current;
        // Slightly under conversational pace and a touch low: this reads out
        // threat scores and place names, and both survive being read calmly.
        utterance.rate = 1.0;
        utterance.pitch = 0.95;

        let settled = false;
        const finish = () => {
          if (settled) return;
          settled = true;
          if (mine === generation.current) {
            outstanding.current = Math.max(0, outstanding.current - 1);
            if (outstanding.current === 0) setSpeaking(false);
          }
          resolve();
        };
        utterance.onend = finish;
        utterance.onerror = finish;

        outstanding.current += 1;
        setSpeaking(true);
        window.speechSynthesis.speak(utterance);

        // Chrome drops long utterances silently and never fires onend, which
        // would leave the microphone gated forever. Release on a generous
        // estimate of the reading time as a backstop.
        window.setTimeout(finish, 2500 + text.length * 90);
      }),
    []
  );

  useEffect(() => cancel, [cancel]);

  return { speak, cancel, speaking };
}

// ── listening ──────────────────────────────────────────────────────────

interface ListenerOptions {
  /** Fires once per finalised utterance. */
  onUtterance: (transcript: string) => void;
  /** Keep the microphone open between utterances (wake-word mode). */
  continuous: boolean;
  /** Hold the microphone closed without tearing down the session — used while
   *  Sentinel is speaking so it does not transcribe itself. */
  paused: boolean;
  lang?: string;
}

export function useListener({ onUtterance, continuous, paused, lang = "en-IN" }: ListenerOptions) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);

  const recognition = useRef<SrInstance | null>(null);
  const wantOn = useRef(false);
  const onUtteranceRef = useRef(onUtterance);
  onUtteranceRef.current = onUtterance;

  const stop = useCallback(() => {
    wantOn.current = false;
    setListening(false);
    setInterim("");
    try {
      recognition.current?.stop();
    } catch {
      /* already stopped */
    }
  }, []);

  const start = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor) {
      setError("This browser has no speech recognition. Chrome or Edge is needed.");
      return;
    }
    wantOn.current = true;
    setError(null);

    if (recognition.current) {
      try {
        recognition.current.start();
        return;
      } catch {
        // InvalidStateError means it is already running — nothing to do.
        return;
      }
    }

    const rec = new Ctor();
    rec.continuous = continuous;
    rec.interimResults = true;
    rec.lang = lang;
    rec.maxAlternatives = 1;

    rec.onstart = () => setListening(true);

    rec.onresult = (event) => {
      let finalText = "";
      let pending = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const text = result[0]?.transcript ?? "";
        if (result.isFinal) finalText += text;
        else pending += text;
      }
      setInterim(pending);
      if (finalText.trim()) {
        setInterim("");
        onUtteranceRef.current(finalText.trim());
      }
    };

    rec.onerror = (event) => {
      if (event.error === "no-speech" || event.error === "aborted") return;
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        wantOn.current = false;
        setError("Microphone access was denied. Allow it in the browser's site settings.");
      } else if (event.error === "network") {
        setError("Speech recognition is offline — it needs a network connection.");
      } else {
        setError(`Speech recognition error: ${event.error}`);
      }
      setListening(false);
    };

    rec.onend = () => {
      setListening(false);
      setInterim("");
      // Chrome ends the session on silence. Reopen it only if we still want to
      // be listening, or "stop" would never actually stop.
      if (wantOn.current && continuous) {
        window.setTimeout(() => {
          if (!wantOn.current) return;
          try {
            rec.start();
          } catch {
            /* raced with a deliberate stop */
          }
        }, 250);
      }
    };

    recognition.current = rec;
    try {
      rec.start();
    } catch {
      /* start() on an already-started instance */
    }
  }, [continuous, lang]);

  // While Sentinel talks, close the microphone. `wantOn` is left untouched so
  // the session resumes on its own when speech finishes.
  useEffect(() => {
    if (!paused || !recognition.current) return;
    try {
      recognition.current.abort();
    } catch {
      /* not running */
    }
    setListening(false);
    return () => {
      if (!wantOn.current) return;
      window.setTimeout(() => {
        if (!wantOn.current) return;
        try {
          recognition.current?.start();
        } catch {
          /* already running */
        }
      }, 350);
    };
  }, [paused]);

  // The mode is fixed at construction, so switching it needs a new instance.
  useEffect(() => {
    if (!recognition.current) return;
    const wasOn = wantOn.current;
    try {
      recognition.current.abort();
    } catch {
      /* not running */
    }
    recognition.current = null;
    if (wasOn) start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [continuous]);

  useEffect(
    () => () => {
      wantOn.current = false;
      try {
        recognition.current?.abort();
      } catch {
        /* not running */
      }
    },
    []
  );

  return { listening, interim, error, start, stop, clearError: () => setError(null) };
}

/* A wake word used to live here. It is gone with the toggle that armed it:
 * the assistant now listens from sign-in, and requiring an officer to say
 * "Hey Sentinel" before every question was friction in exchange for nothing —
 * the same microphone was open either way. */
