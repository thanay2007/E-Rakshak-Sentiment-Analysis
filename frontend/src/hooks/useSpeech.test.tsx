import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { scriptLang, useListener } from "./useSpeech";

class FakeRecognition extends EventTarget {
  static latest: FakeRecognition | null = null;
  continuous = false;
  interimResults = false;
  lang = "";
  maxAlternatives = 0;
  onresult: ((event: Event & { resultIndex: number; results: unknown }) => void) | null = null;
  onerror: ((event: Event & { error: string; message: string }) => void) | null = null;
  onend: (() => void) | null = null;
  onstart: (() => void) | null = null;

  constructor() {
    super();
    FakeRecognition.latest = this;
  }

  start() { this.onstart?.(); }
  stop() { this.onend?.(); }
  abort() { this.onend?.(); }

  emitFinal(text: string) {
    this.onresult?.({
      resultIndex: 0,
      results: { length: 1, 0: { isFinal: true, 0: { transcript: text }, length: 1 } },
    } as Event & { resultIndex: number; results: unknown });
  }
}

function ListenerHarness({ onUtterance }: { onUtterance: (text: string) => void }) {
  const listener = useListener({ onUtterance, continuous: true, paused: false });
  return <button onClick={listener.start}>{listener.listening ? "listening" : "start"}</button>;
}

describe("useListener", () => {
  beforeEach(() => {
    (window as unknown as { SpeechRecognition: typeof FakeRecognition }).SpeechRecognition = FakeRecognition;
    FakeRecognition.latest = null;
  });

  afterEach(() => {
    delete (window as unknown as { SpeechRecognition?: unknown }).SpeechRecognition;
  });

  it("delivers a final browser transcript after a user-initiated start", () => {
    const onUtterance = vi.fn();
    render(<ListenerHarness onUtterance={onUtterance} />);

    act(() => screen.getByRole("button", { name: "start" }).click());
    expect(screen.getByRole("button")).toHaveTextContent("listening");

    act(() => FakeRecognition.latest?.emitFinal("Brief me on current threats"));
    expect(onUtterance).toHaveBeenCalledWith("Brief me on current threats");
  });
});

describe("scriptLang", () => {
  it("reads English, Hinglish and Gujlish with an Indian-English voice", () => {
    expect(scriptLang("How many alerts in Surat today?")).toBe("en");
    expect(scriptLang("Aaj Surat mein kitne alerts aaye?")).toBe("en");
    expect(scriptLang("Aaje Rajkot ma ketla posts aavya?")).toBe("en");
  });

  it("reads Devanagari with a Hindi voice and Gujarati script with a Gujarati one", () => {
    expect(scriptLang("आज सूरत में कितने अलर्ट आए?")).toBe("hi");
    expect(scriptLang("આજે રાજકોટમાં કેટલી પોસ્ટ આવી?")).toBe("gu");
  });

  it("goes by the dominant script when a sentence mixes them", () => {
    expect(scriptLang("Threat score सूरत के लिए बहुत ज़्यादा है")).toBe("hi");
  });
});
