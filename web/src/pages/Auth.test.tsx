import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { json, renderPage, stubFetch } from "../test-utils";
import Login from "./Login";
import Register from "./Register";

const ME = { user_id: "u1", email: "sara@example.com", role: "patient", patient_id: "p1", doctor_id: null };

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("signing up", () => {
  it("needs the data-processing box, sends it, and goes where the patient was heading", async () => {
    const calls = stubFetch({ "POST /api/auth/register": () => json(ME, 201) });
    renderPage(<Register />, { path: "/register", at: "/register?next=/book/d1" });

    await userEvent.type(screen.getByLabelText("Full name"), "Sara Ali");
    await userEvent.type(screen.getByLabelText("Email"), "sara@example.com");
    await userEvent.type(screen.getByLabelText(/^Password/), "correct horse battery");
    const submit = screen.getByRole("button", { name: "Sign up" });
    expect(submit).toBeDisabled();

    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(submit);

    await waitFor(() => expect(screen.getAllByTestId("where").map((w) => w.textContent)).toContain("/book/d1"));
    const sent = calls.find((c) => c.url === "/api/auth/register")!.body as Record<string, unknown>;
    expect(sent).toMatchObject({ full_name: "Sara Ali", email: "sara@example.com", accept_data_processing: true });
    expect(sent.phone).toBeUndefined();
  });

  it("says when the email already has an account", async () => {
    stubFetch({ "POST /api/auth/register": () => json({ detail: "taken" }, 409) });
    renderPage(<Register />, { path: "/register" });

    await userEvent.type(screen.getByLabelText("Full name"), "Sara Ali");
    await userEvent.type(screen.getByLabelText("Email"), "sara@example.com");
    await userEvent.type(screen.getByLabelText(/^Password/), "correct horse battery");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Sign up" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("An account with this email already exists");
  });
});

describe("logging in", () => {
  it("sends a doctor to their schedule and a wrong password gets one message", async () => {
    let attempts = 0;
    stubFetch({
      "POST /api/auth/login": () => (++attempts === 1 ? json({ detail: "no" }, 401) : json({ ...ME, role: "doctor", doctor_id: "d1" })),
    });
    renderPage(<Login />, { path: "/login" });

    await userEvent.type(screen.getByLabelText("Email"), "dr@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong password");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Log in" }));
    await waitFor(() => expect(screen.getAllByTestId("where").map((w) => w.textContent)).toContain("/doctor"));
  });
});
