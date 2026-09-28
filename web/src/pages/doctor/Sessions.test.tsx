import { screen, waitFor, within } from "@testing-library/react";
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

const appointment = (id: string, start: string, status: string, reason: string | null = null) => ({
  appointment_id: id,
  doctor_id: "d1",
  patient_id: "p1",
  start,
  end: start,
  status,
  mode: "in_person",
  hold_expires_at: null,
  reason_for_visit: reason,
});

const entry = (id: string, kind: string, content: string, visibility = "doctor_only") => ({
  entry_id: id,
  doctor_id: "d1",
  kind,
  content,
  visibility,
  source_type: null,
  source_id: null,
  appointment_id: "a1",
  occurred_at: "2026-07-28T06:05:00Z",
});

const PAST = {
  appointment: appointment("a1", "2026-07-28T06:00:00Z", "completed", "Palpitations at night"),
  summary: {
    note: entry("h1", "visit_summary", "Subjective: Palpitations.\n\nPlan: Bisoprolol 2.5 mg."),
    patient: entry("h2", "visit_summary", "Start bisoprolol once a day.", "patient_visible"),
  },
  recordings: [
    {
      consultation_id: "c1",
      patient_id: "p1",
      appointment_id: "a1",
      status: "approved",
      error: null,
      part_count: 1,
      share_with_patient: true,
      started_at: "2026-07-28T06:02:00Z",
      approved_at: "2026-07-28T07:00:00Z",
      created_at: "2026-07-28T06:02:00Z",
      transcript: entry("h3", "visit_transcript", "[00:00] How are you?"),
    },
  ],
  documents: [
    {
      document_id: "doc1",
      patient_id: "p1",
      doctor_id: "d1",
      kind: "report",
      filename: "ecg_report.txt",
      mime: "text/plain",
      size_bytes: 9,
      page_count: 1,
      status: "indexed",
      error: null,
      visibility: "doctor_only",
      ai_description: null,
      ai_label: "AI description",
      appointment_id: "a1",
      created_at: "2026-07-28T06:30:00Z",
    },
  ],
  notes: [entry("h4", "note", "Cut caffeine to one cup.")],
  counts: { recordings: 1, documents: 1, notes: 3 },
};

const empty = (id: string, start: string, status: string) => ({
  appointment: appointment(id, start, status),
  summary: { note: null, patient: null },
  recordings: [],
  documents: [],
  notes: [],
  counts: { recordings: 0, documents: 0, notes: 0 },
});

function file(overrides: object = {}) {
  return {
    patient: SARA,
    timezone: "Africa/Cairo",
    sessions: [empty("a3", "2099-01-06T08:00:00Z", "confirmed"), empty("a2", "2026-09-08T08:00:00Z", "no_show"), PAST],
    general: { notes: [{ ...entry("h9", "note", "Father had an MI at 55."), appointment_id: null }], documents: [] },
    questions: [],
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("a patient's file by session", () => {
  it("opens the latest past session, showing its summary, recordings, documents and notes in that order", async () => {
    stubFetch({ "GET /api/doctor/patients/p1/visits": () => file() });
    renderPage(<PatientPage />, { path: "/doctor/patients/:patientId", at: "/doctor/patients/p1" });

    const session = (await screen.findByText("Palpitations at night")).closest("details")!;
    expect(session).toHaveAttribute("open");
    const parts = within(session)
      .getAllByRole("region")
      .map((r) => r.getAttribute("aria-label"));
    expect(parts).toEqual(["Summary", "Recordings", "Documents", "Notes"]);
    expect(within(session).getByText("Plan: Bisoprolol 2.5 mg.")).toBeInTheDocument();
    expect(within(session).getByText("Start bisoprolol once a day.")).toBeInTheDocument();
    expect(within(session).getByText("[00:00] How are you?").closest("details")).not.toHaveAttribute("open");
    expect(within(session).getByText("ecg_report.txt")).toBeInTheDocument();
    expect(within(session).getByText("Cut caffeine to one cup.")).toBeInTheDocument();

    // the upcoming one is closed and says so; the no-show with nothing in it is one line
    const upcoming = document.getElementById("session-a3")!;
    expect(upcoming).not.toHaveAttribute("open");
    expect(within(upcoming).getByText("Upcoming")).toBeInTheDocument();
    expect(document.getElementById("session-a2")!.tagName).toBe("DIV");
    // what belongs to no session
    expect(screen.getByText("Not tied to a session")).toBeInTheDocument();
    // nothing to answer: no questions panel
    expect(screen.queryByRole("region", { name: "Questions waiting for you" })).not.toBeInTheDocument();
  });

  it("adds to a session through one menu, one form at a time, filed under that session", async () => {
    const calls = stubFetch({
      "GET /api/doctor/patients/p1/visits": () => file(),
      "POST /api/doctor/patients/p1/history": () => json({ entry_id: "h5" }, 201),
    });
    renderPage(<PatientPage />, { path: "/doctor/patients/:patientId", at: "/doctor/patients/p1" });

    const session = (await screen.findByText("Palpitations at night")).closest("details")!;
    expect(within(session).queryByRole("textbox")).not.toBeInTheDocument();
    await userEvent.click(within(session).getByRole("button", { name: "Note" }));
    expect(within(session).getByRole("textbox", { name: "Add note" })).toBeInTheDocument();
    await userEvent.click(within(session).getByRole("button", { name: "Document" }));
    expect(within(session).queryByRole("textbox", { name: "Add note" })).not.toBeInTheDocument();

    await userEvent.click(within(session).getByRole("button", { name: "Note" }));
    await userEvent.type(within(session).getByRole("textbox", { name: "Add note" }), "BP 124/80 at the end.");
    await userEvent.click(within(session).getByRole("button", { name: "Add note" }));

    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ content: "BP 124/80 at the end.", appointment_id: "a1" }),
    );
  });

  it("files a note added outside any session under none", async () => {
    const calls = stubFetch({
      "GET /api/doctor/patients/p1/visits": () => file(),
      "POST /api/doctor/patients/p1/history": () => json({ entry_id: "h6" }, 201),
    });
    renderPage(<PatientPage />, { path: "/doctor/patients/:patientId", at: "/doctor/patients/p1" });

    const general = (await screen.findByText("Not tied to a session")).closest("details")!;
    await userEvent.click(within(general).getByText("Not tied to a session"));
    expect(within(general).getByText("Father had an MI at 55.")).toBeInTheDocument();
    await userEvent.click(within(general).getByRole("button", { name: "Note" }));
    await userEvent.type(within(general).getByRole("textbox", { name: "Add note" }), "Non-smoker.");
    await userEvent.click(within(general).getByRole("button", { name: "Add note" }));

    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ appointment_id: null }));
  });

  it("puts open questions first, and keeps the full timeline behind its tab", async () => {
    const questions = [
      {
        escalation_id: "e1",
        patient_id: "p1",
        patient_name: "Sara",
        reason: "sensitive",
        status: "open",
        question: "Can I stop my pills?",
        doctor_reply: null,
        nudged_at: null,
        answered_at: null,
        created_at: "2026-09-28T06:43:00Z",
      },
    ];
    stubFetch({
      "GET /api/doctor/patients/p1/visits": () => file({ questions }),
      "GET /api/doctor/patients/p1/timeline": () => ({
        patient: SARA,
        timezone: "Africa/Cairo",
        items: [{ type: "history", at: "2026-07-28T06:05:00Z", ...entry("h4", "note", "Cut caffeine to one cup.") }],
      }),
    });
    renderPage(<PatientPage />, { path: "/doctor/patients/:patientId", at: "/doctor/patients/p1" });

    const panel = await screen.findByRole("region", { name: "Questions waiting for you" });
    expect(within(panel).getByRole("textbox", { name: /your reply/i })).toHaveAccessibleDescription("Can I stop my pills?");

    await userEvent.click(screen.getByRole("tab", { name: "Timeline" }));
    const timeline = await screen.findByRole("tabpanel", { name: "Timeline" });
    expect(await within(timeline).findByText("Cut caffeine to one cup.")).toBeInTheDocument();
    expect(screen.queryByText("Not tied to a session")).not.toBeInTheDocument();
  });

  it("opens the session a link names", async () => {
    stubFetch({ "GET /api/doctor/patients/p1/visits": () => file() });
    renderPage(<PatientPage />, { path: "/doctor/patients/:patientId", at: "/doctor/patients/p1#session-a3" });

    await screen.findByText("Palpitations at night");
    expect(document.getElementById("session-a3")).toHaveAttribute("open");
    expect(screen.getByText("Palpitations at night").closest("details")).not.toHaveAttribute("open");
  });
});

describe("one session on its own page", () => {
  it("shows the session opened", async () => {
    stubFetch({
      "GET /api/doctor/patients/p1/visits/a1": () => ({ patient: SARA, timezone: "Africa/Cairo", session: PAST }),
    });
    renderPage(<Visit />, { path: "/doctor/patients/:patientId/visits/:appointmentId", at: "/doctor/patients/p1/visits/a1" });

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Sara");
    expect(screen.getByText("Palpitations at night").closest("details")).toHaveAttribute("open");
    expect(screen.getByRole("link", { name: "Back" })).toHaveAttribute("href", "/doctor/patients/p1#session-a1");
  });

  it("says so when the visit is not this patient's", async () => {
    stubFetch({ "GET /api/doctor/patients/p1/visits/zz": () => json({ detail: "not found" }, 404) });
    renderPage(<Visit />, { path: "/doctor/patients/:patientId/visits/:appointmentId", at: "/doctor/patients/p1/visits/zz" });

    expect(await screen.findByText("This visit is not in this patient's file.")).toBeInTheDocument();
  });
});

describe("a session with little in it", () => {
  it("leaves out the parts with nothing in them, but always says where the summary stands", async () => {
    stubFetch({
      "GET /api/doctor/patients/p1/visits/a9": () => ({
        patient: SARA,
        timezone: "Africa/Cairo",
        session: { ...PAST, summary: { note: null, patient: null }, recordings: [], documents: [] },
      }),
    });
    renderPage(<Visit />, { path: "/doctor/patients/:patientId/visits/:appointmentId", at: "/doctor/patients/p1/visits/a9" });

    await screen.findByText("No summary yet.");
    expect(screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"))).toEqual(["Summary", "Notes"]);
  });
});
