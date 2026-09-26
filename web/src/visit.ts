import type { Appointment } from "./api";

// the same window the consultation service enforces (logic/online.py)
const EARLY_MS = 15 * 60_000;
const LATE_MS = 30 * 60_000;

/** Whether this appointment's room can be joined now: a confirmed online visit, from 15 minutes before to 30 after. */
export function joinable(a: Pick<Appointment, "mode" | "status" | "start" | "end">, now = Date.now()): boolean {
  return (
    a.mode === "online" &&
    a.status === "confirmed" &&
    now >= new Date(a.start).getTime() - EARLY_MS &&
    now <= new Date(a.end).getTime() + LATE_MS
  );
}
