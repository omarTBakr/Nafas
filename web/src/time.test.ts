import { clinicClock, clinicDate, clinicInstant, offsetMinutes, upcomingDates } from "./time";

describe("clinic time", () => {
  it("attaches the clinic's offset, not the browser's", () => {
    expect(clinicInstant("2026-10-07", "17:40", "Africa/Cairo")).toBe("2026-10-07T17:40:00+03:00");
  });

  it("follows Cairo's daylight saving on either side of the change", () => {
    // Egypt moves to UTC+3 on the last Friday of April and back on the last Thursday of October
    expect(clinicInstant("2026-04-23", "17:00", "Africa/Cairo")).toBe("2026-04-23T17:00:00+02:00");
    expect(clinicInstant("2026-04-30", "17:00", "Africa/Cairo")).toBe("2026-04-30T17:00:00+03:00");
    expect(clinicInstant("2026-10-30", "17:00", "Africa/Cairo")).toBe("2026-10-30T17:00:00+02:00");
  });

  it("round-trips: the instant reads back as the same clinic date and clock", () => {
    const iso = clinicInstant("2026-10-07", "09:05", "Africa/Cairo");
    expect(clinicDate(iso, "Africa/Cairo")).toBe("2026-10-07");
    expect(clinicClock(iso, "Africa/Cairo", "en-GB")).toBe("09:05");
  });

  it("measures offsets west of UTC too", () => {
    expect(offsetMinutes(new Date("2026-07-01T12:00:00Z"), "America/New_York")).toBe(-240);
    expect(clinicInstant("2026-07-01", "08:30", "America/New_York")).toBe("2026-07-01T08:30:00-04:00");
  });

  it("lists upcoming clinic dates across a month end", () => {
    const from = new Date("2026-09-29T21:30:00Z"); // already the 30th in Cairo
    expect(upcomingDates(3, "Africa/Cairo", from)).toEqual(["2026-09-30", "2026-10-01", "2026-10-02"]);
  });
});
