import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useVoiceSession } from "./useVoiceSession";

class FakeSocket {
  static OPEN = 1;
  static instances: FakeSocket[] = [];
  readyState = 1;
  binaryType = "";
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => { this.readyState = 3; this.onclose?.(); });
  constructor() { FakeSocket.instances.push(this); }
  packet(packet: object) { this.onmessage?.({ data: JSON.stringify(packet) }); }
}

class FakeAudio {
  static latest: FakeAudio;
  state = "running";
  sampleRate = 48000;
  currentTime = 0;
  destination = {};
  resume = vi.fn(async () => { this.state = "running"; });
  close = vi.fn(async () => { this.state = "closed"; });
  constructor() { FakeAudio.latest = this; }
  createMediaStreamSource() { return { connect: vi.fn(), disconnect: vi.fn() }; }
  createScriptProcessor() { return { connect: (node: unknown) => node, onaudioprocess: null }; }
  createGain() { return { gain: { value: 0 }, connect: () => ({ connect: vi.fn() }) }; }
}

const getUserMedia = vi.fn();
beforeEach(() => {
  FakeSocket.instances = [];
  getUserMedia.mockReset().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] });
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("AudioContext", FakeAudio);
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

const options = { token: "test-token", page: "/app", enabled: true };

it("retries microphone access when the officer clicks after a denial", async () => {
  getUserMedia.mockRejectedValueOnce(new Error("permission denied"));
  const { result } = renderHook(() => useVoiceSession(options));
  await waitFor(() => expect(result.current.micBlocked).toBeTruthy());
  await act(async () => { await result.current.activate(); });
  expect(getUserMedia).toHaveBeenCalledTimes(2);
  expect(result.current.micBlocked).toBeNull();
  expect(FakeSocket.instances).toHaveLength(1);
});

it("resumes suspended audio on activation without opening a second session", async () => {
  const { result } = renderHook(() => useVoiceSession(options));
  await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
  FakeAudio.latest.state = "suspended";
  await act(async () => { await result.current.activate(); });
  expect(FakeAudio.latest.resume).toHaveBeenCalledOnce();
  expect(result.current.needsGesture).toBe(false);
  expect(FakeSocket.instances).toHaveLength(1);
});

it("reconnects when the provider drops but the browser socket is still open", async () => {
  const { result } = renderHook(() => useVoiceSession(options));
  await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
  vi.useFakeTimers();
  act(() => FakeSocket.instances[0].packet({ type: "PipelineErrorPacket", message: "The voice link dropped. Reconnecting." }));
  expect(FakeSocket.instances[0].close).toHaveBeenCalledOnce();
  await act(async () => { await vi.advanceTimersByTimeAsync(800); });
  expect(FakeSocket.instances).toHaveLength(2);
  act(() => FakeSocket.instances[1].packet({ type: "InitializationCompletedPacket", stt_provider: "gemini_live", tts_provider: "gemini_live" }));
  expect(result.current.connected).toBe(true);
  expect(result.current.error).toBeNull();
});

it("shows connection failures sent by the backend", async () => {
  const { result } = renderHook(() => useVoiceSession(options));
  await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
  act(() => FakeSocket.instances[0].packet({ type: "error", message: "Voice provider could not start." }));
  expect(result.current.error).toBe("Voice provider could not start.");
});
