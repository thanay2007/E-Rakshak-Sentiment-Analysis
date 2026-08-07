/** The browser end of the real-time voice channel.
 *
 *  Counterpart to `backend/app/services/voice/` — a port of the client side of
 *  Rapida's streamer. The assistant is always on: this connects itself as soon
 *  as an officer is signed in, and reconnects itself when the channel drops.
 *  Four jobs, and each has one detail that decides whether the thing feels
 *  alive or broken:
 *
 *  1. **Capture.** An AudioWorklet takes microphone audio, downmixes to mono
 *     and posts blocks to the main thread, which converts to PCM16 and sends
 *     them as binary frames. A worklet rather than the deprecated
 *     ScriptProcessor because the latter runs on the main thread: any React
 *     render during speech drops audio, and dropped frames are dropped words.
 *
 *  2. **Playback.** Synthesised audio arrives as a stream of chunks that must
 *     play gap-free. Scheduling each one with `start(0)` produces a click at
 *     every boundary, so a running cursor tracks when the previous chunk ends
 *     and the next is scheduled exactly there.
 *
 *  3. **Not hearing itself.** The speakers are pointed at the microphone. The
 *     browser's own echo canceller helps and is left on, but it is not a
 *     guarantee — it does not reliably cover speech synthesis, and it degrades
 *     badly with loud external speakers. So this is half-duplex by
 *     construction: **while the assistant is audible, not one frame is sent
 *     upstream.** Nothing that is not sent can be transcribed, which makes
 *     self-hearing impossible rather than unlikely. The server is told when
 *     the speakers are live and gates the recogniser for the same window.
 *
 *  4. **Barge-in.** Gating the microphone would normally cost interruption, so
 *     the decision moves here, where the reference signal is: we know exactly
 *     what samples we are playing, so we know roughly how loud the echo of
 *     them can be. Sustained microphone energy well above that is a person
 *     talking over the answer, not the answer. Playback stops immediately —
 *     every scheduled source node is retained so it can be stopped, and the
 *     cursor is reset. Without the retained references audio keeps playing for
 *     however long was already queued, which is exactly the moment it must not.
 *
 *  Sample rate is negotiated, not assumed. `AudioContext.sampleRate` is
 *  whatever the output device runs at — 44100 or 48000 — and it is sent in the
 *  handshake so the server resamples correctly. Assuming 16 kHz does not
 *  error; it transcribes a chipmunk.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { API_BASE } from "../services/api";

/** The worklet, inlined as a blob URL: it must be a separate module file, and
 *  a blob avoids a build-config change and a second network request.
 *
 *  It buffers to ~21 ms blocks rather than posting every 128-sample render
 *  quantum. Unbuffered, that is a websocket frame every 2.7 ms — four hundred
 *  a second, each with its own header — for no gain: the server reframes to
 *  20 ms on arrival regardless. */
const CAPTURE_WORKLET = `
const BLOCK = 1024;
class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = new Float32Array(BLOCK);
    this.filled = 0;
  }
  process(inputs) {
    const input = inputs[0];
    if (!input || !input.length) return true;
    const channels = input.length;
    const frames = input[0].length;
    for (let i = 0; i < frames; i += 1) {
      // Average the channels rather than taking the first: a laptop array mic
      // can put most of the speaker's energy in either one.
      let sample = 0;
      for (let c = 0; c < channels; c += 1) sample += input[c][i] / channels;
      this.block[this.filled] = sample;
      this.filled += 1;
      if (this.filled === BLOCK) {
        // A copy, because the block is reused for the next window.
        this.port.postMessage(this.block.slice(0));
        this.filled = 0;
      }
    }
    return true;
  }
}
registerProcessor('capture-processor', CaptureProcessor);
`;

export type VoiceState = "idle" | "connecting" | "listening" | "thinking" | "speaking";

export interface VoiceTurn {
  id: string;
  role: "officer" | "sentinel";
  text: string;
  interim?: boolean;
  tools?: string[];
}

interface Options {
  token: string;
  page: string;
  /** Fires when the assistant's `navigate` tool resolved a page. */
  onNavigate?: (path: string) => void;
  /** Server-side TTS is not always configured; when it is not, the browser
   *  speaks. It must resolve when the utterance actually *finishes*, because
   *  that is what un-gates the microphone. */
  speakLocally?: (text: string) => Promise<void>;
  /** Stop browser speech now — used when barge-in fires. */
  cancelLocalSpeech?: () => void;
  /** False releases the microphone entirely and closes the channel. */
  enabled: boolean;
  /** Silence the assistant without closing the channel. Synthesised audio is
   *  dropped rather than played, so it also never reaches the microphone. */
  muted?: boolean;
}

// ── half-duplex tuning ─────────────────────────────────────────────────────
// All in the same units the capture path produces: RMS of a ~21 ms block of
// mono float samples, so 0.02 is a quiet room and 0.1 is someone talking.

/** Silence after the speakers stop before the microphone reopens. Covers the
 *  room's reverberation tail; below about 200 ms the last word of an answer
 *  comes back as the first word of a question. */
const REOPEN_DELAY_MS = 250;

/** How long the speakers must be quiet before the server is told they are.
 *  Streaming synthesis underruns for a few milliseconds between chunks, and
 *  without this the channel reports stop/start on every one of them. */
const QUIET_DEBOUNCE_MS = 180;

/** Sustained loud speech needed to talk over the assistant. Long enough to
 *  exclude a cough, a door or a chair; short enough that interrupting feels
 *  like it worked immediately. */
const BARGE_IN_MS = 340;

/** Nothing quieter than this is a person, however quiet the room is. Stops a
 *  near-silent room from making the barge-in threshold meaninglessly low. */
const ABSOLUTE_SPEECH_FLOOR = 0.022;

/** How far above the room's noise floor speech has to be. */
const NOISE_MARGIN = 5;

/** How far above the assistant's own level a voice has to be to count as
 *  someone else. The echo reaching the microphone is attenuated by the room
 *  and again by the browser's canceller, so requiring better than parity with
 *  the *source* level is a deliberately generous margin. */
const ECHO_MARGIN = 2.2;

/** Assumed echo level while the browser is speaking, where there is no sample
 *  buffer to measure. Speech synthesis does not go through our AudioContext,
 *  so this is the one path with no reference signal. */
const BROWSER_ECHO_ESTIMATE = 0.09;

/** Reconnect backoff. The assistant is meant to be permanently available, so a
 *  dropped socket is a transient to ride out, not a state to sit in. */
const RECONNECT_MIN_MS = 800;
const RECONNECT_MAX_MS = 15_000;

function floatToPcm16(input: Float32Array): ArrayBuffer {
  const out = new DataView(new ArrayBuffer(input.length * 2));
  for (let i = 0; i < input.length; i += 1) {
    // Clip rather than let it wrap: a wrapped sample is an audible click on
    // every overdriven frame.
    const s = Math.max(-1, Math.min(1, input[i]));
    out.setInt16(i * 2, s * 0x7fff, true);
  }
  return out.buffer;
}

function rmsOf(samples: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
  return Math.sqrt(sum / samples.length);
}

/** One scheduled chunk of the assistant's voice, kept so the capture path can
 *  ask "how loud is what is coming out of the speakers right now". */
interface Scheduled {
  start: number;
  end: number;
  rms: number;
}

export function useVoiceSession({
  token, page, onNavigate, speakLocally, cancelLocalSpeech, enabled,
  muted = false,
}: Options) {
  const [state, setState] = useState<VoiceState>("idle");
  const [connected, setConnected] = useState(false);
  const [turns, setTurns] = useState<VoiceTurn[]>([]);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [providers, setProviders] = useState<{ stt: string; tts: string } | null>(null);
  /** Autoplay policy: a reloaded tab has no user activation, so the context
   *  starts suspended and the assistant would be silently mute. The UI says so
   *  rather than appearing broken. */
  const [needsGesture, setNeedsGesture] = useState(false);
  /** No microphone: denied, absent, or an insecure origin. Distinct from a
   *  dropped connection, because it is the officer who has to fix it and they
   *  can only do that if they are told. "Reconnecting…" forever is the worst
   *  of both — it looks like the app is working on it, and nothing is. */
  const [micBlocked, setMicBlocked] = useState<string | null>(null);
  /** Whether the officer currently has to say "Sentinel" to be heard.
   *
   *  The microphone is open from sign-in, so most speech in a control room is
   *  not addressed to the console and the server ignores it. An officer who is
   *  not told that cannot tell the difference between being filtered and being
   *  broken — so the state is shown, and it comes from the server rather than
   *  a local timer, because the follow-up window is extended by speech only
   *  the server adjudicates. */
  const [wake, setWake] = useState<{ required: boolean; listening: boolean }>({
    required: false, listening: false,
  });
  /** Smoothed microphone level, for the UI. Updated ten times a second, not
   *  fifty: this drives an animation, and re-rendering React on the audio path
   *  is what the worklet exists to avoid. */
  const [level, setLevel] = useState(0);

  const socket = useRef<WebSocket | null>(null);
  const audioContext = useRef<AudioContext | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const workletNode = useRef<AudioWorkletNode | null>(null);
  const sourceNode = useRef<MediaStreamAudioSourceNode | null>(null);

  /** Live intent. Read on the audio path and in reconnect timers, where a
   *  stale closure over `enabled` would either leak a microphone or refuse to
   *  reopen one.
   *
   *  Written only from the effect that owns the connection, never during
   *  render. That is not style: React's StrictMode mounts, unmounts and
   *  remounts every component in development, so the teardown runs between two
   *  mounts with no render in between. Setting this during render left it
   *  false for the second mount, `connect()` returned at its first line, and
   *  the assistant sat on "connecting…" forever with the microphone open. */
  const running = useRef(false);
  /** A connection attempt is between "asked for the microphone" and "has a
   *  socket". Nothing else may start one during that window. */
  const opening = useRef(false);
  const retries = useRef(0);
  const retryTimer = useRef<number | null>(null);
  const greeted = useRef(false);

  // Playback scheduling. `cursor` is when the last queued chunk ends; `sources`
  // is every node still scheduled, retained solely so barge-in can stop them.
  const playbackCursor = useRef(0);
  const sources = useRef<AudioBufferSourceNode[]>([]);
  const scheduled = useRef<Scheduled[]>([]);

  // Half-duplex bookkeeping.
  const localSpeaking = useRef(false);
  /** Browser utterances started and not finished. A reply is spoken a sentence
   *  at a time, so several overlap, and the microphone must stay shut until the
   *  last of them ends — not the first. */
  const localPending = useRef(0);
  const speakersReported = useRef(false);
  const lastLiveAt = useRef(0);
  const noiseFloor = useRef(0.01);
  const bargeMs = useRef(0);
  const lastLevelPush = useRef(0);

  const providersRef = useRef<{ stt: string; tts: string } | null>(null);
  const wakeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pageRef = useRef(page);
  pageRef.current = page;
  const mutedRef = useRef(muted);
  mutedRef.current = muted;

  const push = useCallback((turn: VoiceTurn) => {
    setTurns((prev) => [...prev.slice(-29), turn]);
  }, []);

  const send = useCallback((payload: Record<string, unknown>) => {
    if (socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify(payload));
    }
  }, []);

  // ── is the assistant audible right now ───────────────────────────────────

  /** The honest answer, derived rather than tracked: either the browser is
   *  mid-utterance, or there are samples scheduled beyond the playback clock. */
  const speakersLive = useCallback(() => {
    if (localSpeaking.current) return true;
    const context = audioContext.current;
    if (!context) return false;
    return playbackCursor.current > context.currentTime + 0.005;
  }, []);

  /** Digital level of what is playing at this instant — the reference signal
   *  the barge-in threshold is built on. */
  const echoLevel = useCallback(() => {
    if (localSpeaking.current) return BROWSER_ECHO_ESTIMATE;
    const context = audioContext.current;
    if (!context) return 0;
    const now = context.currentTime;
    scheduled.current = scheduled.current.filter((chunk) => chunk.end > now - 0.5);
    const playing = scheduled.current.find(
      (chunk) => chunk.start <= now && chunk.end >= now
    );
    return playing?.rms ?? 0;
  }, []);

  /** Tell the server when the speakers start and stop. This is the frame that
   *  keeps the recogniser closed for the real duration of an answer rather
   *  than the duration of the send — see `state.set_client_playback`. */
  const reportPlayback = useCallback(() => {
    if (speakersLive()) {
      lastLiveAt.current = Date.now();
      if (!speakersReported.current) {
        speakersReported.current = true;
        send({ type: "playback", active: true });
      }
      return;
    }
    if (
      speakersReported.current &&
      Date.now() - lastLiveAt.current > QUIET_DEBOUNCE_MS
    ) {
      speakersReported.current = false;
      send({ type: "playback", active: false });
    }
  }, [send, speakersLive]);

  /** True while nothing may be sent upstream. */
  const microphoneGated = useCallback(
    () =>
      speakersReported.current ||
      speakersLive() ||
      Date.now() - lastLiveAt.current < REOPEN_DELAY_MS,
    [speakersLive]
  );

  // ── playback ─────────────────────────────────────────────────────────────

  const stopPlayback = useCallback(() => {
    sources.current.forEach((node) => {
      try {
        node.stop();
      } catch {
        /* already finished */
      }
    });
    sources.current = [];
    scheduled.current = [];
    playbackCursor.current = 0;
    localSpeaking.current = false;
    localPending.current = 0;
    lastLiveAt.current = Date.now();
    if (speakersReported.current) {
      speakersReported.current = false;
      send({ type: "playback", active: false });
    }
  }, [send]);

  const enqueueAudio = useCallback(
    (payload: ArrayBuffer) => {
      const context = audioContext.current;
      if (!context || payload.byteLength === 0) return;
      // Muted drops the audio here rather than turning the volume down: audio
      // that is never scheduled is audio the microphone can never hear.
      if (mutedRef.current) return;

      const pcm = new Int16Array(payload);
      const buffer = context.createBuffer(1, pcm.length, 16000);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < pcm.length; i += 1) channel[i] = pcm[i] / 0x8000;

      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);

      // Schedule at the end of what is already queued, not "now". A small lead
      // absorbs jitter without being audible as delay.
      const startAt = Math.max(context.currentTime + 0.02, playbackCursor.current);
      source.start(startAt);
      playbackCursor.current = startAt + buffer.duration;

      // Remembered so the capture path can compare the microphone against what
      // the speakers are actually doing at that moment.
      scheduled.current.push({
        start: startAt,
        end: startAt + buffer.duration,
        rms: rmsOf(channel),
      });

      sources.current.push(source);
      source.onended = () => {
        sources.current = sources.current.filter((n) => n !== source);
      };
      reportPlayback();
    },
    [reportPlayback]
  );

  // ── barge-in ─────────────────────────────────────────────────────────────

  const interrupt = useCallback(() => {
    bargeMs.current = 0;
    cancelLocalSpeech?.();
    stopPlayback();
    send({ type: "interrupt" });
    setState("listening");
  }, [cancelLocalSpeech, send, stopPlayback]);

  /** One captured block: gate, meter, and decide whether someone is talking
   *  over the answer. Runs about fifty times a second, so it allocates
   *  nothing and touches React state at most ten times a second. */
  const handleBlock = useCallback(
    (block: Float32Array) => {
      const ws = socket.current;
      const loudness = rmsOf(block);
      const now = Date.now();

      if (now - lastLevelPush.current > 100) {
        lastLevelPush.current = now;
        setLevel(loudness);
      }

      reportPlayback();

      if (microphoneGated()) {
        // Half duplex: nothing leaves while the assistant is audible. The only
        // question left is whether the officer is talking over it.
        const echo = echoLevel();
        const threshold = Math.max(
          ABSOLUTE_SPEECH_FLOOR,
          noiseFloor.current * NOISE_MARGIN,
          echo * ECHO_MARGIN
        );
        if (loudness > threshold) {
          bargeMs.current += (block.length / (audioContext.current?.sampleRate ?? 48000)) * 1000;
          if (bargeMs.current >= BARGE_IN_MS) interrupt();
        } else {
          bargeMs.current = 0;
        }
        return;
      }

      bargeMs.current = 0;
      // The noise floor is only learned from clean audio — never while the
      // assistant's own voice is in the room, or it learns the assistant.
      // Down fast, up slowly: a room gets quiet in an instant and noisy over
      // minutes, and over-estimating the floor deafens the barge-in check.
      noiseFloor.current =
        loudness < noiseFloor.current
          ? noiseFloor.current * 0.9 + loudness * 0.1
          : noiseFloor.current * 0.999 + loudness * 0.001;
      noiseFloor.current = Math.max(noiseFloor.current, 0.002);

      if (ws?.readyState === WebSocket.OPEN) ws.send(floatToPcm16(block));
    },
    [echoLevel, interrupt, microphoneGated, reportPlayback]
  );

  // ── inbound control ──────────────────────────────────────────────────────

  const handleMessage = useCallback(
    (raw: string) => {
      let packet: Record<string, unknown>;
      try {
        packet = JSON.parse(raw);
      } catch {
        return;
      }
      const type = packet.type as string;

      switch (type) {
        case "InitializationCompletedPacket": {
          const negotiated = {
            stt: String(packet.stt_provider ?? ""),
            tts: String(packet.tts_provider ?? ""),
          };
          providersRef.current = negotiated;
          setProviders(negotiated);
          setConnected(true);
          setState("idle");
          setError(null);
          retries.current = 0;
          greeted.current = true;
          break;
        }

        case "InterimEndOfSpeechPacket":
          setInterim(String(packet.text ?? ""));
          setState("listening");
          break;

        case "SpeechToTextPacket":
          if (packet.is_final) {
            setInterim("");
            push({
              id: `${packet.context_id}-user`,
              role: "officer",
              text: String(packet.text ?? ""),
            });
          } else {
            setInterim(String(packet.text ?? ""));
          }
          break;

        case "WakeStatePacket": {
          setWake({ required: Boolean(packet.required),
                    listening: Boolean(packet.listening) });
          // The server sends the window's remaining life rather than a later
          // "it closed" packet, so the label expires here. Any extension
          // arrives as a fresh packet and restarts this timer.
          if (wakeTimer.current) clearTimeout(wakeTimer.current);
          if (packet.listening && packet.expires_in > 0) {
            wakeTimer.current = setTimeout(
              () => setWake((w) => ({ ...w, listening: false })),
              packet.expires_in * 1000);
          }
          break;
        }

        case "TurnChangePacket":
          // Our own playback state is the better answer for "speaking", since
          // the server declares the turn over when the last packet is *sent*.
          if (packet.speaker === "assistant") setState("speaking");
          else if (!speakersLive()) setState("idle");
          break;

        case "LLMToolInvokedPacket":
          setState("thinking");
          break;

        case "LLMResponseDonePacket":
          push({
            id: `${packet.context_id}-reply`,
            role: "sentinel",
            text: String(packet.text ?? ""),
          });
          break;

        case "TextToSpeechTextPacket": {
          // With no server-side synthesiser configured, this is the instruction
          // to speak locally. The text is already normalised for speech by the
          // backend chain. Holding `localSpeaking` for the true duration of the
          // utterance is what keeps the microphone shut while it plays.
          if (providersRef.current?.tts !== "browser" || !speakLocally) break;
          const text = String(packet.text ?? "");
          if (!text.trim()) break;
          localPending.current += 1;
          localSpeaking.current = true;
          lastLiveAt.current = Date.now();
          setState("speaking");
          reportPlayback();
          void speakLocally(text).finally(() => {
            localPending.current = Math.max(0, localPending.current - 1);
            if (localPending.current === 0) {
              localSpeaking.current = false;
              lastLiveAt.current = Date.now();
              setState((current) => (current === "speaking" ? "idle" : current));
            }
            reportPlayback();
          });
          break;
        }

        case "LLMNavigatePacket":
          if (packet.path) onNavigate?.(String(packet.path));
          break;

        case "InterruptionDetectedPacket":
          cancelLocalSpeech?.();
          stopPlayback();
          setState("listening");
          break;

        case "TextToSpeechDonePacket":
          // Sent, not heard. The state only returns to idle once the speakers
          // are actually quiet.
          if (!speakersLive()) setState("idle");
          break;

        case "PipelineErrorPacket":
          setError(String(packet.message ?? "Voice pipeline error"));
          break;

        default:
          break;
      }
    },
    [cancelLocalSpeech, onNavigate, push, reportPlayback, speakLocally,
     speakersLive, stopPlayback]
  );

  // ── the microphone ───────────────────────────────────────────────────────

  // The socket and the worklet are wired once and live across many renders, so
  // every handler they call goes through a ref. Capturing the handler itself
  // would freeze the version that existed when the channel opened — and a
  // conversation outlives a great many renders.
  const handleBlockRef = useRef(handleBlock);
  handleBlockRef.current = handleBlock;
  const handleMessageRef = useRef(handleMessage);
  handleMessageRef.current = handleMessage;
  const enqueueAudioRef = useRef(enqueueAudio);
  enqueueAudioRef.current = enqueueAudio;

  /** In flight, so overlapping callers share one acquisition. Without it a
   *  StrictMode remount — or any reconnect that races the first attempt — opens
   *  a second microphone whose refs are immediately overwritten, leaving a
   *  MediaStream nothing can ever stop and a recording indicator that stays
   *  lit after the assistant is switched off. */
  const acquiring = useRef<Promise<AudioContext | null> | null>(null);

  const acquireAudio = useCallback(async (): Promise<AudioContext | null> => {

    // Absent on an insecure origin, which is a real deployment case: served
    // over plain HTTP to a workstation, there is no getUserMedia at all and
    // the reason is not something an officer could ever guess.
    if (!navigator.mediaDevices?.getUserMedia) {
      const reason =
        "This page needs to be served over HTTPS for the microphone to work.";
      setMicBlocked(reason);
      setError(reason);
      return null;
    }

    let micStream: MediaStream;
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          // The browser's own front end runs before capture and is better than
          // ours, so it is left on. It is help, not a guarantee — the gate in
          // `handleBlock` is what actually prevents self-hearing.
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch {
      const reason =
        "Microphone access was denied. Allow it in the browser's site settings to talk to Sentinel.";
      setMicBlocked(reason);
      setError(reason);
      return null;
    }
    stream.current = micStream;
    setMicBlocked(null);

    const context = new AudioContext();
    audioContext.current = context;

    // A tab restored without a click has no user activation, so the context is
    // suspended and playback is silent. Resume on the first interaction rather
    // than leaving the assistant apparently mute.
    if (context.state === "suspended") {
      setNeedsGesture(true);
      const resume = () => {
        void context.resume().then(() => setNeedsGesture(false));
        window.removeEventListener("pointerdown", resume);
        window.removeEventListener("keydown", resume);
      };
      window.addEventListener("pointerdown", resume);
      window.addEventListener("keydown", resume);
    }

    const blob = new Blob([CAPTURE_WORKLET], { type: "application/javascript" });
    const workletUrl = URL.createObjectURL(blob);
    try {
      await context.audioWorklet.addModule(workletUrl);
    } finally {
      URL.revokeObjectURL(workletUrl);
    }

    const source = context.createMediaStreamSource(micStream);
    const node = new AudioWorkletNode(context, "capture-processor");
    node.port.onmessage = (event: MessageEvent<Float32Array>) =>
      handleBlockRef.current(event.data);
    source.connect(node);
    // Connect to destination with no gain: some browsers suspend a worklet
    // whose output reaches nothing. This routes silence, not a feedback loop.
    const mute = context.createGain();
    mute.gain.value = 0;
    node.connect(mute).connect(context.destination);

    sourceNode.current = source;
    workletNode.current = node;
    return context;
  }, []);

  /** Opens the microphone once and keeps it. Reconnecting the socket must not
   *  re-prompt for permission or re-flash the recording indicator. */
  const ensureAudio = useCallback((): Promise<AudioContext | null> => {
    if (audioContext.current && stream.current) {
      return Promise.resolve(audioContext.current);
    }
    if (acquiring.current) return acquiring.current;
    const attempt = acquireAudio().finally(() => {
      acquiring.current = null;
    });
    acquiring.current = attempt;
    return attempt;
  }, [acquireAudio]);

  const releaseAudio = useCallback(() => {
    workletNode.current?.disconnect();
    workletNode.current = null;
    sourceNode.current?.disconnect();
    sourceNode.current = null;
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    void audioContext.current?.close();
    audioContext.current = null;
  }, []);

  // ── connect ──────────────────────────────────────────────────────────────

  /** Declared ahead of `connect` because the reconnect timer inside it calls
   *  back into the current version of itself. */
  const connectRef = useRef<() => Promise<void>>(async () => {});

  const connect = useCallback(async () => {
    if (!running.current || !token) return;
    if (socket.current && socket.current.readyState <= WebSocket.OPEN) return;
    // There is a microphone prompt's worth of await between here and the
    // socket existing, and both the supervisor and a retry can arrive during
    // it. Two sockets would mean two sessions against one concurrency cap.
    if (opening.current) return;
    opening.current = true;

    setState("connecting");
    let context: AudioContext | null;
    try {
      context = await ensureAudio();
    } finally {
      opening.current = false;
    }
    if (!context || !running.current) {
      // No microphone is a dead end until the officer acts, so stop pretending
      // to be mid-connection. Toggling the microphone control retries.
      setState("idle");
      return;
    }

    const ws = new WebSocket(`${API_BASE.replace(/^http/, "ws")}/ws/voice`);
    ws.binaryType = "arraybuffer";
    socket.current = ws;

    ws.onopen = () => {
      // Token in the first frame, never the query string — query strings land
      // in access logs, proxy logs and browser history.
      ws.send(
        JSON.stringify({
          type: "auth",
          token,
          page: pageRef.current,
          sample_rate: context.sampleRate,
          // Only the first connection of a sitting is greeted; the reconnects
          // after an idle close are meant to be invisible.
          greet: !greeted.current,
        })
      );
    };

    ws.onmessage = (event) => {
      if (typeof event.data === "string") handleMessageRef.current(event.data);
      else enqueueAudioRef.current(event.data as ArrayBuffer);
    };

    ws.onerror = () => {
      /* onclose follows, and it owns the retry */
    };

    ws.onclose = () => {
      socket.current = null;
      speakersReported.current = false;
      setConnected(false);
      setState("idle");
      if (!running.current) return;
      // Always on means always coming back. The server recycles idle sessions
      // by design, so a close is usually routine rather than a fault.
      retries.current += 1;
      const wait = Math.min(
        RECONNECT_MIN_MS * 2 ** (retries.current - 1),
        RECONNECT_MAX_MS
      );
      retryTimer.current = window.setTimeout(() => void connectRef.current(), wait);
    };
  }, [ensureAudio, token]);
  connectRef.current = connect;

  const disconnect = useCallback(() => {
    if (retryTimer.current !== null) {
      window.clearTimeout(retryTimer.current);
      retryTimer.current = null;
    }
    if (wakeTimer.current !== null) {
      clearTimeout(wakeTimer.current);
      wakeTimer.current = null;
    }
    cancelLocalSpeech?.();
    stopPlayback();
    const ws = socket.current;
    socket.current = null;
    ws?.close();
    releaseAudio();
    setConnected(false);
    setState("idle");
    setInterim("");
    setLevel(0);
  }, [cancelLocalSpeech, releaseAudio, stopPlayback]);

  /** The whole of "it starts by itself": mounted with a token, it runs. */
  useEffect(() => {
    running.current = enabled && Boolean(token);
    if (running.current) void connect();
    else disconnect();
    // `connect`/`disconnect` are rebuilt whenever a handler identity changes;
    // depending on them here would tear the microphone down mid-conversation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, token]);

  /** The supervisor. "Always on" cannot rest on every failure path remembering
   *  to schedule a retry — one that forgets is an assistant that is silently
   *  dead until the page is reloaded, which is exactly how this looked in
   *  development. So the invariant is checked on a timer instead: if it should
   *  be connected and there is neither a socket nor a retry pending, connect.
   *
   *  Cheap, and it covers the cases no `onclose` ever fires for — a permission
   *  prompt the officer finally answered, a laptop resuming from sleep, a
   *  connection attempt that raced a teardown. */
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!running.current) return;
      if (socket.current || retryTimer.current !== null) return;
      if (micBlocked) return;             // needs the officer, not another try
      void connectRef.current();
    }, 4000);
    return () => window.clearInterval(timer);
  }, [micBlocked]);

  // Declared after the connection effect so StrictMode's cleanup ordering is
  // the reverse of setup: this tears down last and re-arms first.
  useEffect(
    () => () => {
      running.current = false;
      disconnect();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    []
  );

  // ── outbound ─────────────────────────────────────────────────────────────

  const ask = useCallback(
    (text: string) => {
      if (!text.trim()) return;
      push({ id: `${Date.now()}-user`, role: "officer", text });
      setState("thinking");
      send({ type: "text", text });
    },
    [push, send]
  );

  const endTurn = useCallback(() => send({ type: "end_turn" }), [send]);

  return {
    state, connected, turns, interim, error, providers, level, needsGesture,
    micBlocked, wake,
    /** True while the microphone is deliberately shut because the assistant is
     *  audible — the UI says "speaking", not "listening", and means it. */
    speaking: state === "speaking",
    connect, disconnect, ask, interrupt, endTurn,
    clearError: () => setError(null),
  };
}
