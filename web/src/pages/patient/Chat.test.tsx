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
      vi.fn(async (_url: string, init?: RequestInit) =>
        init?.method === "POST" ? json({ detail: "the assistant is unavailable" }, 503) : json([]),
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
