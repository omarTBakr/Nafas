import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { I18nProvider } from "../../i18n";
import ConsultationPage from "./Consultation";

const DRAFT = {
  subjective: "Palpitations for two weeks.",
  objective: "BP 150/95.",
  assessment: "Hypertension.",
  plan: "Start amlodipine.",
  diagnoses: [{ name: "Hypertension", status: "known" }],
  medications: [{ name: "Amlodipine", dose: "5 mg", frequency: "daily", change: "started" }],
  allergies: [],
  patient_summary: "Your blood pressure is high.",
  uncertain: ["the dose may have been 10 mg"],
};
const DETAIL = {
  consultation_id: "c1",
  patient_id: "p1",
  appointment_id: null,
  status: "draft_ready",
  error: null,
  part_count: 2,
  share_with_patient: false,
  started_at: "2026-09-26T10:00:00Z",
  approved_at: null,
  created_at: "2026-09-26T10:00:00Z",
  transcript: [{ start: 61, end: 65, text: "عندي خفقان" }],
  draft: DRAFT,
  approved: null,
  model: "m",
  prompt_version: "soap-v1",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

it("shows the model's doubts and the transcript, and approves the doctor's edited note", async () => {
  const posted: [string, unknown][] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posted.push([url, JSON.parse(String(init.body))]);
        return json({ ...DETAIL, status: "filing" });
      }
      return json(posted.length ? { ...DETAIL, status: "filing" } : DETAIL);
    }),
  );
  localStorage.setItem("nafas.lang", "en");
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={["/doctor/consultations/c1"]}>
        <Routes>
          <Route path="/doctor/consultations/:consultationId" element={<ConsultationPage />} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  );

  expect(await screen.findByText("the dose may have been 10 mg")).toBeInTheDocument();
  expect(screen.getByText("01:01")).toBeInTheDocument();
  const plan = screen.getByLabelText("Plan");
  await userEvent.clear(plan);
  await userEvent.type(plan, "Start amlodipine 10 mg.");
  await userEvent.click(screen.getByLabelText(/Send the summary to the patient/));
  await userEvent.click(screen.getByRole("button", { name: "Approve and file" }));

  await waitFor(() => expect(posted).toHaveLength(1));
  const [url, body] = posted[0] as [string, { note: typeof DRAFT; share_with_patient: boolean }];
  expect(url).toBe("/api/doctor/consultations/c1/approve");
  expect(body.share_with_patient).toBe(true);
  expect(body.note.plan).toBe("Start amlodipine 10 mg.");
  expect(body.note.medications).toEqual(DRAFT.medications);
  expect(await screen.findByText("Filing to the record")).toBeInTheDocument();
});
