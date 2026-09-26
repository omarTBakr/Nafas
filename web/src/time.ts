// Clinic time. Every time the app shows or takes is wall-clock time in the
// doctor's zone, whatever zone the browser is in: "17:40" means 17:40 at the
// clinic. These helpers convert between that and exact instants.

/** The UTC offset, in minutes, that `timeZone` has at `instant`. */
export function offsetMinutes(instant: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(instant);
  const get = (type: string) => Number(parts.find((p) => p.type === type)!.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return Math.round((asUtc - instant.getTime()) / 60000);
}

/**
 * The instant at which it is `date` `time` ("2026-10-07", "17:40") in `timeZone`,
 * as an ISO string with that zone's offset — what the API expects.
 *
 * Two passes settle the offset, so a date on the far side of a daylight-saving
 * change from today still gets its own offset.
 */
export function clinicInstant(date: string, time: string, timeZone: string): string {
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  const wall = Date.UTC(y, m - 1, d, hh, mm);

  let offset = offsetMinutes(new Date(wall), timeZone);
  offset = offsetMinutes(new Date(wall - offset * 60000), timeZone);

  const sign = offset >= 0 ? "+" : "-";
  const abs = Math.abs(offset);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date}T${pad(hh)}:${pad(mm)}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

/** The calendar date ("2026-10-07") an instant falls on at the clinic. */
export function clinicDate(instant: Date | string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(instant),
  );
}

/** "17:40" at the clinic. */
export function clinicClock(instant: Date | string, timeZone: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { timeZone, hour: "2-digit", minute: "2-digit" }).format(new Date(instant));
}

/** "Wednesday 7 October" at the clinic, in the reader's language. */
export function clinicDay(instant: Date | string, timeZone: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { timeZone, weekday: "long", day: "numeric", month: "long" }).format(
    new Date(instant),
  );
}

/** The next `count` calendar dates at the clinic, starting today. */
export function upcomingDates(count: number, timeZone: string, from = new Date()): string[] {
  const today = clinicDate(from, timeZone);
  const [y, m, d] = today.split("-").map(Number);
  return Array.from({ length: count }, (_, i) => new Date(Date.UTC(y, m - 1, d + i)).toISOString().slice(0, 10));
}
