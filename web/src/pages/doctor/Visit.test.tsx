import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { json, renderPage, stubFetch } from "../../test-utils";
import PatientPage from "./Patient";
import Visit from "./Visit";

const SARA = {
  patient_id: "p1",
  full_name: "Sara",
  date_of_birth: null,
  sex: null,
  phone: null,
  preferred_language: "en",
  first_seen_at: "2026-09-26T00:00:00Z",
};

const APPOINTMENT = {
  appointment_id: "a1",
  doctor_id: "d1",
  patient_id: "p1",
  start: "2026-09-30T14:00:00Z",
  end: "2026-09-30T14:20:00Z",
  status: "completed",
  mode: "in_person",
  hold_expires_at: null,
  reason_for_visit: "Chest tightness",
};

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("a patient's visits", () => {
  it("lists each visit with what was filed under it, and opens one on its own page", async () => {
    stubFetch({
      "GET /api/doctor/patients/p1/timeline": () => ({ patient: SARA, timezone: "Africa/Cairo", items: [] }),
      "GET /api/doctor/patients/p1/visits": () => ({
        patient: SARA,
        timezone: "Africa/Cairo",
        visits: [{ ...APPOINTMENT, recordings: 1, notes: 5, documents: 2 }],
      }),
    });
    renderPage(<PatientPage />, { path: "/doctor/patients/:patientId", at: "/doctor/patients/p1" });

    const visits = await screen.findByRole("region", { name: "Visits" });
    const link = await waitFor(() => {
      const found = visits.querySelector("a");
      expect(found).not.toBeNull();
      return found!;
    });
    expect(link).toHaveTextContent("Recordings 1 · Notes 5 · Documents 2");
    expect(link).toHaveTextContent("Wednesday 30 September · 17:00");

    await userEvent.click(link);
    await waitFor(() => expect(screen.getAllByTestId("where").map((w) => w.textContent)).toContain("/doctor/patients/p1/visits/a1"));
  });

  it("shows one visit's recording, notes and documents, and files a note written there under it", async () => {
    const calls = stubFetch({
      "GET /api/doctor/patients/p1/visits/a1": () => ({
        patient: SARA,
        timezone: "Africa/Cairo",
        appointment: APPOINTMENT,
        consultations: [
          {
            consultation_id: "c1",
            patient_id: "p1",
            appointment_id: "a1",
            status: "approved",
            error: null,
            part_count: 1,
            share_with_patient: false,
            started_at: "2026-09-30T14:02:00Z",
            approved_at: "2026-09-30T15:00:00Z",
            created_at: "2026-09-30T14:02:00Z",
          },
        ],
        history: [
          {
            entry_id: "h1",
            doctor_id: "d1",
            kind: "visit_summary",
            content: "Suspected stable angina.",
            visibility: "doctor_only",
            source_type: "consultation",
            source_id: "c1",
            appointment_id: null,
            occurred_at: "2026-09-30T14:00:00Z",
          },
        ],
        documents: [
          {
            document_id: "doc1",
            patient_id: "p1",
            doctor_id: "d1",
            kind: "lab",
            filename: "lipids.pdf",
            mime: "application/pdf",
            size_bytes: 9,
            page_count: 1,
            status: "indexed",
            error: null,
            visibility: "doctor_only",
            ai_description: null,
            ai_label: "AI description",
            appointment_id: "a1",
            created_at: "2026-09-30T14:30:00Z",
          },
        ],
      }),
      "POST /api/doctor/patients/p1/history": () => json({ entry_id: "h2" }, 201),
    });
    renderPage(<Visit />, { path: "/doctor/patients/:patientId/visits/:appointmentId", at: "/doctor/patients/p1/visits/a1" });

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Visit");
    expect(screen.getByText("Chest tightness")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Recordings" })).toHaveTextContent("Recorded visit");
    expect(screen.getByRole("region", { name: "Notes" })).toHaveTextContent("Suspected stable angina.");
    expect(screen.getByRole("region", { name: "Documents" })).toHaveTextContent("lipids.pdf");

    await userEvent.type(screen.getByRole("textbox", { name: "Add note" }), "Walks 20 minutes a day.");
    await userEvent.click(screen.getByRole("button", { name: "Add note" }));

    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.url === "/api/doctor/patients/p1/history")?.body).toEqual({
        content: "Walks 20 minutes a day.",
        visibility: "doctor_only",
        kind: "note",
        appointment_id: "a1",
      }),
    );
  });

  it("says so when the visit is not this patient's", async () => {
    stubFetch({ "GET /api/doctor/patients/p1/visits/zz": () => json({ detail: "not found" }, 404) });
    renderPage(<Visit />, { path: "/doctor/patients/:patientId/visits/:appointmentId", at: "/doctor/patients/p1/visits/zz" });

    expect(await screen.findByText("This visit is not in this patient's file.")).toBeInTheDocument();
  });
});
