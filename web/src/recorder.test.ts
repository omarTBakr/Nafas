import { ChunkedRecorder } from "./recorder";

/** Stands in for the browser's MediaRecorder: stopping hands over one blob of what was "heard". */
class FakeMediaRecorder {
  static made = 0;
  state: "inactive" | "recording" = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  private listeners: (() => void)[] = [];
  constructor() {
    FakeMediaRecorder.made++;
  }
  static isTypeSupported(type: string) {
    return type === "audio/webm;codecs=opus";
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["sound"], { type: "audio/webm" }) });
    this.onstop?.();
    this.listeners.forEach((l) => l());
  }
  addEventListener(_: string, listener: () => void) {
    this.listeners.push(listener);
  }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("records in parts, each uploaded straight to storage with its offset in the visit", async () => {
  vi.useFakeTimers();
  const parts: { index: number; offset_seconds: number; mime: string }[] = [];
  const puts: string[] = [];
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/parts")) {
        const body = JSON.parse(String(init?.body));
        parts.push(body);
        return json({ index: body.index, upload_url: `https://s3/part-${body.index}`, content_type: body.mime }, 201);
      }
      puts.push(url);
      return new Response(null, { status: 200 });
    }),
  );
  const seen: number[] = [];
  const recorder = new ChunkedRecorder("c1", (p) => seen.push(p.uploaded), 60);

  await recorder.start();
  await vi.advanceTimersByTimeAsync(125_000);
  await recorder.stop();

  expect(parts.map((p) => [p.index, Math.round(p.offset_seconds)])).toEqual([
    [0, 0],
    [1, 60],
    [2, 120],
  ]);
  expect(parts[0].mime).toBe("audio/webm");
  expect(puts).toEqual(["https://s3/part-0", "https://s3/part-1", "https://s3/part-2"]);
  expect(Math.max(...seen)).toBe(3);
});
