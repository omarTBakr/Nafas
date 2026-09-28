import { arabicShare, passages, plainText, Reader, voiceFor } from "./speech";

class FakeUtterance {
  lang = "";
  voice: unknown = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public text: string) {}
}

/** The browser's voice, recording what it was asked to say and finishing each at once. */
function fakeSynthesis(installed = [{ lang: "en-US" }, { lang: "ar-EG" }]) {
  const said: { text: string; lang: string }[] = [];
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  vi.stubGlobal("speechSynthesis", {
    getVoices: () => installed,
    cancel: vi.fn(),
    speak: (u: FakeUtterance) => {
      said.push({ text: u.text, lang: u.lang });
      queueMicrotask(() => u.onend?.());
    },
  });
  return said;
}

/** An Audio element that "plays" a clip and ends straight away. */
function fakeAudio() {
  const played: string[] = [];
  vi.stubGlobal(
    "Audio",
    class {
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onpause: (() => void) | null = null;
      constructor(public src: string) {}
      play() {
        played.push(this.src);
        queueMicrotask(() => this.onended?.());
        return Promise.resolve();
      }
      pause() {}
    },
  );
  // jsdom has no object URLs; only these two are replaced, the rest of URL stays
  Object.assign(URL, { createObjectURL: () => `blob:${played.length}`, revokeObjectURL: () => undefined });
  return played;
}

afterEach(() => vi.unstubAllGlobals());

describe("what is read aloud", () => {
  it("is the words of an answer, without its markup", () => {
    const markdown = "## Plan\n\n- **Bisoprolol** 2.5 mg\n- see [the guideline](https://example.org)\n\n```\ncode\n```";
    expect(plainText(markdown)).toBe("Plan\nBisoprolol 2.5 mg\nsee the guideline");
  });

  it("goes to the dialect voice when it is Arabic, and to the browser's when it has English in it", () => {
    expect(voiceFor("بدأت العلاج يوم الثلاثاء والمتابعة بعد أسبوعين")).toBe("dialect");
    expect(voiceFor("She is on bisoprolol 2.5 mg daily.")).toBe("browser");
    expect(voiceFor("المريضة تأخذ Bisoprolol و Atorvastatin يوميا")).toBe("browser");
    expect(arabicShare("123")).toBe(0);
  });

  it("is split into passages the voice can take, at the ends of sentences", () => {
    const sentence = "هذه جملة قصيرة للتجربة. ";
    const parts = passages(sentence.repeat(40).trim(), 100);
    expect(parts.length).toBeGreaterThan(5);
    expect(parts.every((p) => p.length <= 100 && p.endsWith("."))).toBe(true);
    expect(parts.join(" ")).toBe(sentence.repeat(40).trim());
  });
});

describe("the reader", () => {
  it("plays an Arabic answer in the dialect chosen, passage by passage", async () => {
    const played = fakeAudio();
    const asked: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        asked.push(JSON.parse(String(init?.body)));
        return new Response("RIFF", { status: 200, headers: { "Content-Type": "audio/wav" } });
      }),
    );
    const ended = vi.fn();

    await new Reader().read("بدأت العلاج. والمتابعة بعد أسبوعين.", { dialect: "sa", onEnd: ended });

    expect(asked).toEqual([{ text: "بدأت العلاج. والمتابعة بعد أسبوعين.", dialect: "sa", voice: null }]);
    expect(played).toHaveLength(1);
    expect(ended).toHaveBeenCalledOnce();
  });

  it("reads English in the browser's voice, and never asks the dialect voice", async () => {
    const said = fakeSynthesis();
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);

    await new Reader().read("She is on **bisoprolol**.", { dialect: "eg" });

    expect(said).toEqual([{ text: "She is on bisoprolol.", lang: "en-US" }]);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("falls back to the browser's voice when the dialect voice is unavailable", async () => {
    const said = fakeSynthesis();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 503 })));

    await new Reader().read("المتابعة بعد أسبوعين.", { dialect: "eg" });

    expect(said).toEqual([{ text: "المتابعة بعد أسبوعين.", lang: "ar-EG" }]);
  });

  it("says so, rather than staying silent, when English has no voice in this browser", async () => {
    const said = fakeSynthesis([]);
    vi.useFakeTimers();
    const reading = new Reader().read("She is on bisoprolol.", { dialect: "eg" });
    await vi.advanceTimersByTimeAsync(1500);
    vi.useRealTimers();

    expect(await reading).toBe("no_voice");
    expect(said).toEqual([]);
  });

  it("gives a mostly Arabic answer to the dialect voice when the browser has no voice", async () => {
    fakeSynthesis([]);
    const played = fakeAudio();
    const asked: { text: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        asked.push(JSON.parse(String(init?.body)));
        return new Response("RIFF", { status: 200, headers: { "Content-Type": "audio/wav" } });
      }),
    );
    vi.useFakeTimers();
    const reading = new Reader().read("المريضة تأخذ الدواء مرة يوميا مع Bisoprolol", { dialect: "eg" });
    await vi.advanceTimersByTimeAsync(1500);
    vi.useRealTimers();

    expect(await reading).toBe("done");
    expect(asked).toHaveLength(1);
    expect(played).toHaveLength(1);
  });
});
