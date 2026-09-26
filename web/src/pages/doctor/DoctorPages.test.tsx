import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import App from "../../App";
import { AuthProvider } from "../../auth";
import { I18nProvider } from "../../i18n";
import { json, renderPage, stubFetch } from "../../test-utils";
import NextPatient from "./NextPatient";
import Patients from "./Patients";

const recorder = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), abandon: vi.fn(), made: [] as string[] }));
vi.mock("../../recorder", () => ({
  ChunkedRecorder: class {
    constructor(consultationId: string) {
      recorder.made.push(consultationId);
    }
    start = recorder.start;
    stop = recorder.stop;
    abandon = recorder.abandon;
  },
  recorderType: () => "audio/webm",
}));

// imported after the mock, so it records through the fake
const { default: RecordVisit } = await import("./RecordVisit");

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  recorder.made.length = 0;
  localStorage.clear();
});

describe("recording an in-person visit", () => {
  it("waits for the patient's consent, records, then sends it for a draft", async () => {
    recorder.start.mockResolvedValue(undefined);
    recorder.stop.mockResolvedValue(undefined);
    const calls = stubFetch({
      "POST /api/doctor/patients/p1/consultations": () => json({ consultation_id: "c1", status: "recording" }, 201),
      "POST /api/doctor/consultations/c1/finish": () => ({ consultation_id: "c1", status: "transcribing" }),
    });
    renderPage(<RecordVisit patientId="p1" onChange={() => {}} />, { path: "/doctor/patients/p1" });

    const start = screen.getByRole("button", { name: "Start recording" });
    expect(start).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /agreed to this visit being recorded/ }));
    await userEvent.click(start);

    expect(await screen.findByRole("button", { name: "Finish and send" })).toBeInTheDocument();
    expect(recorder.made).toEqual(["c1"]);
    expect(calls.find((c) => c.url === "/api/doctor/patients/p1/consultations")!.body).toEqual({ evidence: "verbal, in the room" });

    await userEvent.click(screen.getByRole("button", { name: "Finish and send" }));
    await waitFor(() => expect(screen.getAllByTestId("where").map((w) => w.textContent)).toContain("/doctor/consultations/c1"));
    expect(recorder.stop).toHaveBeenCalled();
  });

  it("says so when the microphone cannot start, and discards a recording thrown away", async () => {
    recorder.start.mockRejectedValueOnce(new Error("denied")).mockResolvedValue(undefined);
    const calls = stubFetch({
      "POST /api/doctor/patients/p1/consultations": () => json({ consultation_id: "c2", status: "recording" }, 201),
      "POST /api/doctor/consultations/c2/discard": () => ({ consultation_id: "c2", status: "discarded" }),
    });
    const changed = vi.fn();
    renderPage(<RecordVisit patientId="p1" onChange={changed} />, { path: "/doctor/patients/p1" });

    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Start recording" }));
    expect(await screen.findByText(/Recording could not start/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Start recording" }));
    await userEvent.click(await screen.findByRole("button", { name: "Discard recording" }));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    expect(recorder.abandon).toHaveBeenCalled();
    expect(calls.some((c) => c.url === "/api/doctor/consultations/c2/discard")).toBe(true);
    expect(screen.getByRole("button", { name: "Start recording" })).toBeDisabled();
  });
});

describe("the doctor's lists", () => {
  it("lists their patients, each opening their file", async () => {
    stubFetch({ "GET /api/doctor/patients": () => [{ patient_id: "p1", full_name: "Mona Ali", first_seen_at: "2026-09-01T10:00:00Z" }] });
    renderPage(<Patients />);

    const row = await screen.findByRole("link", { name: /Mona Ali/ });
    expect(row).toHaveAttribute("href", "/doctor/patients/p1");
  });

  it("briefs the doctor on who is next, or says the day is done", async () => {
    let done = false;
    stubFetch({
      "GET /api/doctor/next": () =>
        done
          ? { appointment: null, timezone: "Africa/Cairo" }
          : {
              appointment: { appointment_id: "a1", start: "2026-09-26T14:40:00Z", reason_for_visit: "palpitations" },
              timezone: "Africa/Cairo",
              patient: { patient_id: "p1", full_name: "Mona Ali" },
              brief: {
                last_visit: null,
                recent_entries: [{ entry_id: "e1", content: "BP 150/95" }],
                open_questions: [{ escalation_id: "q1" }],
                documents: 2,
              },
            },
    });
    const { unmount } = renderPage(<NextPatient />);

    expect(await screen.findByText(/Mona Ali/)).toBeInTheDocument();
    expect(screen.getByText("17:40")).toBeInTheDocument();
    expect(screen.getByText("BP 150/95")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open file" })).toHaveAttribute("href", "/doctor/patients/p1");
    unmount();

    done = true;
    renderPage(<NextPatient />);
    expect(await screen.findByText("No confirmed appointments left today")).toBeInTheDocument();
  });
});

describe("the app's doors", () => {
  it("sends a patient who opens a doctor's page back to theirs, and a stranger to log in", async () => {
    stubFetch({
      "GET /api/auth/me": () => ({ user_id: "u1", email: "s@example.com", role: "patient", patient_id: "p1", doctor_id: null }),
      "GET /api/doctors": () => [],
      "GET /api/notifications": () => [],
      "GET /api/specializations": () => [],
    });
    localStorage.setItem("nafas.lang", "en");
    await act(async () => {
      render(
        <I18nProvider>
          <AuthProvider>
            <MemoryRouter initialEntries={["/doctor/patients"]}>
              <App />
            </MemoryRouter>
          </AuthProvider>
        </I18nProvider>,
      );
    });

    await waitFor(() => expect(screen.queryByRole("heading", { name: "My patients" })).not.toBeInTheDocument());
    expect(screen.getByRole("link", { name: "My records" })).toBeInTheDocument();
  });
});
