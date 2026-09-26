import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { I18nProvider } from "../../i18n";
import Inbox from "./Inbox";

const OPEN = [
  {
    escalation_id: "e1",
    patient_id: "p1",
    patient_name: "Sara",
    reason: "emergency",
    status: "open",
    question: "I have crushing chest pain",
    doctor_reply: null,
    nudged_at: null,
    answered_at: null,
    created_at: "2026-09-26T10:00:00Z",
  },
  {
    escalation_id: "e2",
    patient_id: "p2",
    patient_name: null,
    reason: "sensitive",
    status: "open",
    question: "Can I double my dose?",
    doctor_reply: null,
    nudged_at: "2026-09-27T10:00:00Z",
    answered_at: null,
    created_at: "2026-09-26T09:00:00Z",
  },
];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

it("lists the questions waiting, and a reply goes to the patient and clears it", async () => {
  let answered = false;
  const posted: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posted.push([url, JSON.parse(String(init.body))]);
        answered = true;
        return json({ ...OPEN[1], status: "answered" });
      }
      if (url.includes("status=open")) return json(answered ? [OPEN[0]] : OPEN);
      return json([]);
    }),
  );
  localStorage.setItem("nafas.lang", "en");
  render(
    <I18nProvider>
      <Inbox />
    </I18nProvider>,
  );

  expect(await screen.findByText("I have crushing chest pain")).toBeInTheDocument();
  expect(screen.getByText("Emergency").closest("article")).toHaveClass("urgent");
  // a patient not (yet) under the doctor's care has no name to show
  expect(screen.getByText("Patient")).toBeInTheDocument();
  expect(screen.getByText(/The patient was told the answer has not come yet/)).toBeInTheDocument();

  const [, second] = screen.getAllByLabelText(/Your reply/);
  await userEvent.type(second, "No, keep the same dose until Wednesday.");
  await userEvent.click(screen.getAllByRole("button", { name: "Send reply" })[1]);

  await waitFor(() => expect(screen.queryByText("Can I double my dose?")).not.toBeInTheDocument());
  expect(posted).toEqual([["/api/doctor/escalations/e2/reply", { reply: "No, keep the same dose until Wednesday." }]]);
});
