import { joinable } from "./visit";

const at = (iso: string) => new Date(iso).getTime();
const visit = { mode: "online" as const, status: "confirmed" as const, start: "2026-10-01T10:00:00Z", end: "2026-10-01T10:20:00Z" };

it("opens a confirmed online visit from 15 minutes before to 30 after", () => {
  expect(joinable(visit, at("2026-10-01T09:44:00Z"))).toBe(false);
  expect(joinable(visit, at("2026-10-01T09:45:00Z"))).toBe(true);
  expect(joinable(visit, at("2026-10-01T10:50:00Z"))).toBe(true);
  expect(joinable(visit, at("2026-10-01T10:51:00Z"))).toBe(false);
  expect(joinable({ ...visit, mode: "in_person" }, at("2026-10-01T10:00:00Z"))).toBe(false);
  expect(joinable({ ...visit, status: "held" }, at("2026-10-01T10:00:00Z"))).toBe(false);
});
