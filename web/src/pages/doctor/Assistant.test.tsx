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
