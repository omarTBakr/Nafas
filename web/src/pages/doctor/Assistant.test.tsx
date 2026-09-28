import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { streamAssistant } from "../../api";
import { I18nProvider } from "../../i18n";
import Assistant from "./Assistant";

/** A streamed response whose chunks cut server-sent events at awkward places, as a network does. */
function streamed(chunks: string[]) {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        chunks.forEach((c) => controller.enqueue(encoder.encode(c)));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

const FRAMES = [
  'event: tool\ndata: {"type":"tool","name":"get_patient_timeline"}\n\n',
  'event: text\ndata: {"type":"text","text":"She is on "}\n\nevent: te',
  'xt\ndata: {"type":"text","text":"bisoprolol."}\n',
  '\nevent: done\ndata: {"type":"done","model":"m","prompt_version":"doctor-chat-v1"}\n\n',
];

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

it("reads every event however the chunks split them", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => streamed(FRAMES)));
  const seen: string[] = [];

  await streamAssistant({ messages: [{ role: "user", content: "?" }] }, (e) => seen.push(e.type === "text" ? e.text : e.type));

  expect(seen).toEqual(["tool", "She is on ", "bisoprolol.", "done"]);
});

it("shows the answer as it streams, for the selected patient", async () => {
  const bodies: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      bodies.push(JSON.parse(String(init?.body)));
      return streamed(FRAMES);
    }),
  );
  localStorage.setItem("nafas.lang", "en");
  render(
    <I18nProvider>
      <Assistant patientId="p1" />
    </I18nProvider>,
  );

  await userEvent.type(screen.getByLabelText("Ask"), "What is she on?");
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));

  expect(await screen.findByText("She is on bisoprolol.")).toBeInTheDocument();
  expect(bodies).toEqual([{ patient_id: "p1", messages: [{ role: "user", content: "What is she on?" }] }]);
});

describe("reading answers aloud", () => {
  const said: string[] = [];

  beforeEach(() => {
    said.length = 0;
    vi.stubGlobal(
      "SpeechSynthesisUtterance",
      class {
        lang = "";
        onend: (() => void) | null = null;
        onerror: (() => void) | null = null;
        constructor(public text: string) {}
      },
    );
    vi.stubGlobal("speechSynthesis", {
      getVoices: () => [{ lang: "en-US" }],
      cancel: vi.fn(),
      // an utterance that never ends by itself: the doctor stops it
      speak: (u: { text: string }) => said.push(u.text),
    });
    vi.stubGlobal("fetch", vi.fn(async () => streamed(FRAMES)));
    localStorage.setItem("nafas.lang", "en");
  });

  it("reads an answer when asked, and stops when asked again", async () => {
    render(
      <I18nProvider>
        <Assistant />
      </I18nProvider>,
    );
    await userEvent.type(screen.getByLabelText("Ask"), "What is she on?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText("She is on bisoprolol.");
    // not read unless asked
    expect(said).toEqual([]);

    await userEvent.click(screen.getByRole("button", { name: "Read aloud" }));
    expect(said).toEqual(["She is on bisoprolol."]);
    const stop = screen.getByRole("button", { name: "Stop reading" });
    expect(stop).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(stop);
    expect(screen.getByRole("button", { name: "Read aloud" })).toHaveAttribute("aria-pressed", "false");
  });

  it("reads each answer as it finishes when the doctor chose so, in the dialect remembered", async () => {
    render(
      <I18nProvider>
        <Assistant />
      </I18nProvider>,
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "Read answers aloud" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Voice dialect" }), "sa");
    await userEvent.type(screen.getByLabelText("Ask"), "What is she on?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    await screen.findByRole("button", { name: "Stop reading" });
    expect(said).toEqual(["She is on bisoprolol."]);
    expect(JSON.parse(localStorage.getItem("nafas.assistantVoice")!)).toEqual({ auto: true, dialect: "sa" });
  });
});

describe("dictating a question", () => {
  function microphone() {
    const stop = vi.fn();
    class FakeRecorder {
      static isTypeSupported = (type: string) => type === "audio/webm;codecs=opus";
      mimeType = "audio/webm;codecs=opus";
      stream = { getTracks: () => [{ stop }] };
      ondataavailable: ((e: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      start() {}
      stop() {
        this.ondataavailable?.({ data: new Blob(["opus-bytes"], { type: this.mimeType }) });
        this.onstop?.();
      }
    }
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop }] })) },
    });
    return stop;
  }

  it("turns the doctor's words into the question, to read over before asking", async () => {
    const stop = microphone();
    const sent: FormData[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === "/api/doctor/transcribe") {
          sent.push(init?.body as FormData);
          return new Response(JSON.stringify({ text: "ما آخر نتيجة تحليل دهون؟", language: "ar" }), { status: 200 });
        }
        return streamed(FRAMES);
      }),
    );
    localStorage.setItem("nafas.lang", "en");
    render(
      <I18nProvider>
        <Assistant />
      </I18nProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Dictate your question" }));
    await userEvent.click(await screen.findByRole("button", { name: "Stop" }));

    expect(await screen.findByDisplayValue("ما آخر نتيجة تحليل دهون؟")).toBeInTheDocument();
    expect(sent).toHaveLength(1);
    expect((sent[0].get("audio") as Blob).type).toBe("audio/webm;codecs=opus");
    // the microphone is released, and nothing is asked until the doctor sends it
    expect(stop).toHaveBeenCalled();
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/doctor/assistant")).toHaveLength(0);
  });

  it("says so when the words could not be turned into text, and keeps what was typed", async () => {
    microphone();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "down", reason: "stt_unavailable" }), { status: 503 })),
    );
    localStorage.setItem("nafas.lang", "en");
    render(
      <I18nProvider>
        <Assistant />
      </I18nProvider>,
    );
    await userEvent.type(screen.getByLabelText("Ask"), "Her last LDL");

    await userEvent.click(screen.getByRole("button", { name: "Dictate your question" }));
    await userEvent.click(await screen.findByRole("button", { name: "Stop" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not turn that into text");
    expect(screen.getByLabelText("Ask")).toHaveValue("Her last LDL");
  });
});
