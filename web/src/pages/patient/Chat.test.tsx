import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { I18nProvider } from "../../i18n";
import Chat from "./Chat";

const HELD = {
  appointment_id: "a1",
  doctor_id: "d1",
  patient_id: "p1",
  start: "2026-10-07T14:40:00+00:00",
  end: "2026-10-07T15:00:00+00:00",
  status: "held",
  mode: "in_person",
  hold_expires_at: "2026-10-07T10:00:00+00:00",
  reason_for_visit: null,
};

const CONSENTED = [
  { consent_id: "c1", kind: "data_processing", doctor_id: null, granted_at: "2026-09-26T00:00:00Z", evidence: "web:consent-v1" },
  { consent_id: "c2", kind: "ai_chat", doctor_id: "d1", granted_at: "2026-09-26T00:00:00Z", evidence: "web:consent-v1" },
];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderChat(onBookingChange = vi.fn()) {
  localStorage.setItem("nafas.lang", "en");
  render(
    <I18nProvider>
      <Chat doctorId="d1" timezone="Africa/Cairo" onBookingChange={onBookingChange} />
    </I18nProvider>,
  );
  return onBookingChange;
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("the chat panel", () => {
  it("shows the reply with the time the assistant held, and confirms it in place", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? "GET"} ${url}`);
        if (url === "/api/me/consents") return json(CONSENTED);
        if (url === "/api/chat/d1/messages" && init?.method === "POST")
          return json({
            conversation_id: "c1",
            message_id: "m2",
            text: "I held Wednesday 5:40 pm for you. Shall I confirm?",
            actions: [{ type: "hold", appointment: HELD }],
            intent: "booking",
            patient_text: "Wednesday 5:40",
            audio_key: null,
          });
        if (url === "/api/chat/d1/messages") return json([]);
        if (url === "/api/appointments/a1/confirm") return json({ ...HELD, status: "confirmed", hold_expires_at: null });
        return json({}, 404);
      }),
    );
    const onBookingChange = renderChat();

    expect(await screen.findByText("AI assistant, not a doctor")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Type your message"), "Wednesday 5:40");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("I held Wednesday 5:40 pm for you. Shall I confirm?")).toBeInTheDocument();
    expect(screen.getByText("Wednesday 5:40")).toBeInTheDocument();
    expect(screen.getByText("Held for you")).toBeInTheDocument();
    // clinic time: 14:40 UTC is 17:40 in Cairo
    expect(screen.getByText(/17:40/)).toBeInTheDocument();
    expect(onBookingChange).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Confirm booking" }));

    await waitFor(() => expect(screen.getByText("Confirmed", { selector: "span.badge" })).toBeInTheDocument());
    expect(calls).toContain("POST /api/appointments/a1/confirm");
  });

  it("keeps the draft and says so when the assistant cannot answer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) =>
        url === "/api/me/consents"
          ? json(CONSENTED)
          : init?.method === "POST"
            ? json({ detail: "the assistant is unavailable" }, 503)
            : json([]),
      ),
    );
    renderChat();

    const input = await screen.findByLabelText("Type your message");
    await userEvent.type(input, "hello");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The assistant is unavailable right now");
    expect(input).toHaveValue("hello");
  });
});

describe("voice notes", () => {
  it("records, sends the note, and plays back both sides", async () => {
    const stop = vi.fn();
    class FakeRecorder {
      static isTypeSupported = (type: string) => type === "audio/webm;codecs=opus";
      mimeType = "audio/webm;codecs=opus";
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
    const sent: FormData[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === "/api/me/consents") return json(CONSENTED);
        if (url === "/api/chat/d1/voice") {
          sent.push(init?.body as FormData);
          return json({
            conversation_id: "c1",
            message_id: "reply-1",
            text: "العيادة في المعادي",
            actions: [],
            intent: "admin",
            patient_text: "العيادة فين؟",
            audio_key: "doctor/d1/patient/p1/voice/reply-1.wav",
            patient_message_id: "note-1",
          });
        }
        return json([]);
      }),
    );
    renderChat();

    await userEvent.click(await screen.findByRole("button", { name: "Record a voice note" }));
    await userEvent.click(screen.getByRole("button", { name: "Stop and send" }));

    expect(await screen.findByText("العيادة في المعادي")).toBeInTheDocument();
    expect(screen.getByText("العيادة فين؟")).toBeInTheDocument();
    expect((sent[0].get("audio") as Blob).type).toBe("audio/webm;codecs=opus");
    // the microphone is released once the note is recorded
    expect(stop).toHaveBeenCalled();
    const players = screen.getAllByLabelText("Voice note");
    expect(players.map((p) => p.getAttribute("src"))).toEqual([
      "/api/chat/d1/messages/note-1/audio",
      "/api/chat/d1/messages/reply-1/audio",
    ]);
  });
});

describe("consent", () => {
  it("asks for what is missing before the chat opens, and records it", async () => {
    const granted: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === "/api/me/consents" && init?.method === "POST") {
          granted.push(JSON.parse(String(init.body)));
          return json(CONSENTED[1], 201);
        }
        if (url === "/api/me/consents") return json([CONSENTED[0]]);
        return json([]);
      }),
    );
    renderChat();

    expect(await screen.findByText(/I agree to chat with an AI assistant/)).toBeInTheDocument();
    // data processing was already given: only the chat consent is asked for
    expect(screen.queryByText(/stores and processes my data/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "I agree" }));

    expect(await screen.findByLabelText("Type your message")).toBeInTheDocument();
    expect(granted).toEqual([{ kind: "ai_chat", doctor_id: "d1" }]);
  });
});
