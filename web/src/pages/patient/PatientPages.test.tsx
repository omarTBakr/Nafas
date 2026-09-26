import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { json, renderPage, stubFetch } from "../../test-utils";
import Notifications from "./Notifications";
import ProfilePage from "./Profile";
import Records from "./Records";

const DOCTOR = {
  doctor_id: "d1",
  full_name_en: "Dr Heart",
  full_name_ar: "د. قلب",
  specialization_code: "cardiology",
  specialization_en: "Cardiology",
  specialization_ar: "قلب",
  languages: ["ar"],
};

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("my records", () => {
  it("shows what the doctors shared, by kind and doctor, and opens a shared document", async () => {
    stubFetch({
      "GET /api/me/records": () => ({
        history: [
          {
            entry_id: "e1",
            doctor_id: "d1",
            kind: "visit_summary",
            content: "Your blood pressure is high; start amlodipine.",
            visibility: "patient_visible",
            source_type: "consultation",
            occurred_at: "2026-09-26T10:00:00Z",
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
            size_bytes: 10,
            page_count: 1,
            status: "indexed",
            error: null,
            visibility: "patient_visible",
            ai_description: null,
            ai_label: "",
            created_at: "2026-09-20T10:00:00Z",
          },
        ],
      }),
      "GET /api/doctors": () => [DOCTOR],
      "GET /api/me/documents/doc1/download": () => ({ url: "https://s3/lipids.pdf" }),
    });
    const opened = vi.fn();
    vi.stubGlobal("open", opened);
    renderPage(<Records />);

    const summary = (await screen.findByText("Your blood pressure is high; start amlodipine.")).closest("article")!;
    expect(within(summary).getByText("Visit summary")).toBeInTheDocument();
    await waitFor(() => expect(within(summary).getByText(/Dr Heart/)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(opened).toHaveBeenCalledWith("https://s3/lipids.pdf", "_blank", "noopener");
  });

  it("says when nothing is shared yet", async () => {
    stubFetch({ "GET /api/me/records": () => ({ history: [], documents: [] }), "GET /api/doctors": () => [] });
    renderPage(<Records />);

    expect(await screen.findByText("Your doctors have not shared anything yet.")).toBeInTheDocument();
  });
});

describe("notifications", () => {
  it("shows each notice in clinic time and marks it read", async () => {
    let read = false;
    const calls = stubFetch({
      "GET /api/notifications": () => [
        {
          notification_id: "n1",
          appointment_id: "a1",
          doctor_id: "d1",
          kind: "confirmed",
          minutes_before: null,
          details: { start: "2026-09-30T14:40:00Z", mode: "in_person", timezone: "Africa/Cairo" },
          read_at: read ? "2026-09-26T11:00:00Z" : null,
          created_at: "2026-09-26T10:00:00Z",
        },
      ],
      "POST /api/notifications/n1/read": () => {
        read = true;
        return json(undefined, 204);
      },
    });
    renderPage(<Notifications />);

    expect(await screen.findByText("Your appointment is confirmed")).toBeInTheDocument();
    // 14:40 UTC is 17:40 at a clinic in Cairo
    expect(screen.getByText(/17:40/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: "Done" })).not.toBeInTheDocument());
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/notifications/n1/read")).toBe(true);
  });
});

describe("the profile", () => {
  it("gives and withdraws the optional service-improvement consent", async () => {
    let consents: { consent_id: string; kind: string; doctor_id: string | null }[] = [
      { consent_id: "c1", kind: "data_processing", doctor_id: null },
    ];
    const calls = stubFetch({
      "GET /api/me/profile": () => ({
        patient_id: "p1",
        full_name: "Sara Ali",
        phone: null,
        preferred_language: "en",
        dialect: null,
        voice: null,
        email: "sara@example.com",
        email_notices: true,
      }),
      "GET /api/me/dialect-suggestion": () => ({ dialect: null }),
      "GET /api/doctors": () => [DOCTOR],
      "GET /api/me/consents": () => consents,
      "POST /api/me/consents": (init) => {
        consents = [...consents, { consent_id: "c2", kind: JSON.parse(String(init!.body)).kind, doctor_id: null }];
        return json(consents[1], 201);
      },
      "POST /api/me/consents/c2/revoke": () => {
        consents = consents.filter((c) => c.consent_id !== "c2");
        return json(undefined, 204);
      },
    });
    renderPage(<ProfilePage />);

    const optIn = await screen.findByRole("checkbox", { name: /parts of my chats and visit notes may be reviewed/ });
    expect(optIn).not.toBeChecked();
    await userEvent.click(optIn);
    await waitFor(() => expect(optIn).toBeChecked());
    expect(calls.find((c) => c.method === "POST" && c.url === "/api/me/consents")!.body).toEqual({ kind: "service_improvement", doctor_id: null });

    await userEvent.click(optIn);
    await waitFor(() => expect(optIn).not.toBeChecked());
    expect(calls.some((c) => c.url === "/api/me/consents/c2/revoke")).toBe(true);
  });
});
