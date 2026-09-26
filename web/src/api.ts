// The gateway's API, typed. Every call is same-origin (the dev server proxies
// /api), so the httpOnly session cookie rides along without any token handling here.

export type Role = "doctor" | "patient" | "admin" | "staff";

/** The wording of the consent texts shown (i18n consentDataProcessing, consentAiChat); recorded with each consent. */
export const CONSENT_VERSION = "consent-v1";

export interface Consent {
  consent_id: string;
  kind: "data_processing" | "ai_chat" | "session_recording";
  doctor_id: string | null;
  granted_at: string;
  evidence: string | null;
}

export interface Me {
  user_id: string;
  email: string;
  role: Role;
  doctor_id: string | null;
  patient_id: string | null;
}

export const DIALECTS = ["eg", "sa", "ma", "bh", "sd", "iq", "lb", "sy", "ly", "ps", "tn", "dz", "ye"] as const;
export type SpokenDialect = (typeof DIALECTS)[number];
export type VoiceGender = "female" | "male";

export interface Profile {
  patient_id: string;
  full_name: string;
  phone: string | null;
  preferred_language: "ar" | "en";
  dialect: SpokenDialect | null;
  voice: VoiceGender | null;
}

export interface Specialization {
  code: string;
  name_en: string;
  name_ar: string;
}

export interface Doctor {
  doctor_id: string;
  full_name_en: string;
  full_name_ar: string;
  specialization_code: string;
  specialization_en: string;
  specialization_ar: string;
  languages: string[];
}

export interface Slot {
  start: string;
  end: string;
}

export interface BookingInfo {
  doctor_id: string;
  timezone: string;
  slot_minutes: number;
  hold_minutes: number;
}

export type Unavailable =
  | "not_whole_minute"
  | "too_soon"
  | "beyond_horizon"
  | "outside_hours"
  | "wrong_mode"
  | "time_off"
  | "taken"
  | "not_bookable"
  | "hold_expired"
  | "invalid_transition"
  | "consent_required";

export interface CheckResult {
  bookable: boolean;
  slot: Slot | null;
  reason: Unavailable | null;
  suggestions: Slot[];
}

export type AppointmentStatus = "held" | "confirmed" | "cancelled" | "completed" | "no_show";

export interface Appointment {
  appointment_id: string;
  doctor_id: string;
  patient_id: string;
  start: string;
  end: string;
  status: AppointmentStatus;
  mode: "in_person" | "online";
  hold_expires_at: string | null;
  reason_for_visit: string | null;
  doctor?: Doctor | null;
  patient_name?: string | null;
  // the doctor's clinic zone, on a patient's list
  timezone?: string;
}

export type Intent = "booking" | "medical" | "admin" | "smalltalk" | "emergency" | "unclear";

export interface ChatMessage {
  message_id: string;
  role: "patient" | "assistant" | "doctor";
  modality: "text" | "voice";
  content: string;
  audio_key: string | null;
  intent: Intent | null;
  created_at: string;
}

export interface ChatAction {
  type: "hold" | "confirmed" | "cancelled";
  appointment: Appointment;
}

export interface ChatReply {
  conversation_id: string;
  message_id: string;
  text: string;
  actions: ChatAction[];
  intent: Intent | null;
  patient_text: string;
  audio_key: string | null;
  patient_message_id: string | null;
}

export type NotificationKind = "confirmed" | "hold_expired" | "reminder" | "cancelled_by_doctor";

export interface AppNotification {
  notification_id: string;
  appointment_id: string;
  doctor_id: string;
  kind: NotificationKind;
  minutes_before: number | null;
  details: { start: string; mode: string; timezone: string };
  read_at: string | null;
  created_at: string;
}

export interface Schedule {
  timezone: string;
  appointments: Appointment[];
}

/**
 * A refusal from the API, carrying the machine-readable reason when there is
 * one, and for a 422 the fields that failed validation (field name → message).
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public reason?: Unavailable,
    public fields: Record<string, string> = {},
  ) {
    super(detail);
  }
}

interface ValidationIssue {
  loc: (string | number)[];
  msg: string;
}

/** FastAPI reports validation errors as a list; turn it into field → message. */
function validationFields(detail: unknown): Record<string, string> {
  if (!Array.isArray(detail)) return {};
  return Object.fromEntries(
    (detail as ValidationIssue[]).map((issue) => [String(issue.loc[issue.loc.length - 1]), issue.msg]),
  );
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  // a FormData body (a voice note) sets its own multipart content type
  const form = body instanceof FormData;
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined || form ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const fields = validationFields(payload.detail);
    const detail =
      typeof payload.detail === "string" ? payload.detail : Object.values(fields).join("; ") || response.statusText;
    throw new ApiError(response.status, detail, payload.reason, fields);
  }
  return payload as T;
}

const query = (params: Record<string, string | number | undefined>) =>
  new URLSearchParams(
    Object.entries(params).filter((e): e is [string, string | number] => e[1] !== undefined) as [string, string][],
  ).toString();

export const api = {
  me: () => call<Me>("GET", "/api/auth/me"),
  login: (email: string, password: string) => call<Me>("POST", "/api/auth/login", { email, password }),
  register: (form: {
    email: string;
    password: string;
    full_name: string;
    preferred_language: "ar" | "en";
    phone?: string;
    dialect?: SpokenDialect;
    accept_data_processing: true;
  }) => call<Me>("POST", "/api/auth/register", { consent_version: CONSENT_VERSION, ...form }),
  profile: () => call<Profile>("GET", "/api/me/profile"),
  updateProfile: (changes: Partial<Omit<Profile, "patient_id">>) => call<Profile>("PATCH", "/api/me/profile", changes),
  logout: () => call<void>("POST", "/api/auth/logout"),

  specializations: () => call<Specialization[]>("GET", "/api/specializations"),
  doctors: (specialization?: string) => call<Doctor[]>("GET", `/api/doctors?${query({ specialization })}`),
  doctor: (id: string) => call<Doctor>("GET", `/api/doctors/${id}`),

  bookingInfo: (doctorId: string) => call<BookingInfo>("GET", `/api/doctors/${doctorId}/booking-info`),
  slots: (doctorId: string, start: Date, end: Date, mode = "in_person") =>
    call<Slot[]>("GET", `/api/doctors/${doctorId}/slots?${query({ start: start.toISOString(), end: end.toISOString(), mode })}`),
  check: (doctorId: string, start: string, mode = "in_person") =>
    call<CheckResult>("GET", `/api/doctors/${doctorId}/check?${query({ start, mode })}`),

  hold: (doctorId: string, start: string, reason?: string, mode = "in_person") =>
    call<Appointment>("POST", "/api/appointments", { doctor_id: doctorId, start, mode, reason_for_visit: reason || null }),
  confirm: (id: string) => call<Appointment>("POST", `/api/appointments/${id}/confirm`),
  cancel: (id: string) => call<Appointment>("POST", `/api/appointments/${id}/cancel`),
  mine: () => call<Appointment[]>("GET", "/api/appointments/mine"),

  chatThread: (doctorId: string) => call<ChatMessage[]>("GET", `/api/chat/${doctorId}/messages`),
  chatSend: (doctorId: string, text: string) => call<ChatReply>("POST", `/api/chat/${doctorId}/messages`, { text }),
  chatVoice: (doctorId: string, audio: Blob) => {
    const form = new FormData();
    form.append("audio", audio, "voice-note");
    return call<ChatReply>("POST", `/api/chat/${doctorId}/voice`, form);
  },
  audioUrl: (doctorId: string, messageId: string) => `/api/chat/${doctorId}/messages/${messageId}/audio`,
  consents: () => call<Consent[]>("GET", "/api/me/consents"),
  grantConsent: (kind: "data_processing" | "ai_chat", doctorId?: string) =>
    call<Consent>("POST", "/api/me/consents", { kind, doctor_id: doctorId ?? null }),
  revokeConsent: (id: string) => call<void>("POST", `/api/me/consents/${id}/revoke`),
  dialectSuggestion: () => call<{ dialect: SpokenDialect | null }>("GET", "/api/me/dialect-suggestion"),

  notifications: (unreadOnly = false) =>
    call<AppNotification[]>("GET", `/api/notifications?${query({ unread_only: String(unreadOnly) })}`),
  readNotification: (id: string) => call<void>("POST", `/api/notifications/${id}/read`),

  noShow: (appointmentId: string) => call<Appointment>("POST", `/api/doctor/appointments/${appointmentId}/no-show`),

  schedule: (start: Date, end: Date) =>
    call<Schedule>("GET", `/api/doctor/schedule?${query({ start: start.toISOString(), end: end.toISOString() })}`),
};
