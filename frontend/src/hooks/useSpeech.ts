/** Web Speech API wrappers for the Sentinel assistant.
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
 *     a stretch of silence and fires `onend` with no error, so wake-word mode
 *     has to restart it — but only when it was not stopped deliberately, or
 *     turning the microphone off would immediately turn it back on.
 *
 *  Privacy, stated plainly because this ships to a police deployment: in
 *  Chrome and Edge this API streams audio to the browser vendor's speech
 *  service. It is not local. That is why wake-word mode is opt-in, off by
 *  default, and announced in the UI rather than buried here.
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

const VOICE_PREFERENCE = [
  // Indian English first: the content is Indian place names and handles, and a
  // en-IN voice pronounces "Vadodara" and "Rajkot" correctly where en-US does not.
  /en[-_]IN/i,
  /en[-_]GB/i,
  /en[-_]/i,
];

function pickVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  for (const pattern of VOICE_PREFERENCE) {
    const hit = voices.find((v) => pattern.test(v.lang));
    if (hit) return hit;
  }
  return voices[0] ?? null;
}

export function useSpeaker() {
  const [speaking, setSpeaking] = useState(false);
  const voiceRef = useRef<SpeechSynthesisVoice | null>(null);

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
        // Cancel anything queued: a burst of alerts should read the newest, not
        // narrate a backlog the officer has already dealt with.
        window.speechSynthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(text);
        if (voiceRef.current) utterance.voice = voiceRef.current;
        utterance.rate = 1.05;
        utterance.pitch = 1;

        let settled = false;
        const finish = () => {
          if (settled) return;
          settled = true;
          setSpeaking(false);
          resolve();
        };
        utterance.onend = finish;
        utterance.onerror = finish;

        setSpeaking(true);
        window.speechSynthesis.speak(utterance);

        // Chrome drops long utterances silently and never fires onend, which
        // would leave the listener paused forever. Release on a generous
        // estimate of the reading time as a backstop.
        window.setTimeout(finish, 2000 + text.length * 90);
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

/** Strip a leading wake word and return the command, or null if none was said.
 *
 *  Matched loosely on purpose: "sentinel" is not a word dictation engines
 *  expect, and they routinely return "sentinal", "central" or "sentinelle".
 *  Being strict here means the assistant simply never answers.
 */
const WAKE = /\b(hey|hi|ok|okay|hello)?\s*(sentinel|sentinal|sentinelle|centinel|sentinels|central)\b[\s,.!?-]*/i;

export function extractCommand(transcript: string): string | null {
  const match = WAKE.exec(transcript);
  if (!match) return null;
  return transcript.slice(match.index + match[0].length).trim();
}
