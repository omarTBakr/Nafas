import { api, ApiError } from "./api";

function respond(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("api errors", () => {
  it("turns FastAPI's validation list into fields, not a bare status text", async () => {
    respond(422, {
      detail: [{ type: "value_error", loc: ["body", "email"], msg: "value is not a valid email address" }],
    });

    const error = await api.register({ email: "x@y.local", password: "p", full_name: "n", preferred_language: "ar", accept_data_processing: true }).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.fields).toEqual({ email: "value is not a valid email address" });
    expect(error.detail).toBe("value is not a valid email address");
  });

  it("keeps the booking reason a refusal carries", async () => {
    respond(409, { detail: "another booking took this time first", reason: "taken" });

    const error = await api.hold("doctor", "2026-10-07T17:40:00+03:00").catch((e) => e);

    expect(error.status).toBe(409);
    expect(error.reason).toBe("taken");
  });
});
