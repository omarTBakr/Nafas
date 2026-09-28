// The gateway's API, typed. Every call is same-origin (the dev server proxies
// /api), so the httpOnly session cookie rides along without any token handling here.

export type Role = "doctor" | "patient" | "admin" | "staff";

/** The wording of the consent texts shown (i18n consentDataProcessing, consentAiChat); recorded with each consent. */
export const CONSENT_VERSION = "consent-v1";

export interface Consent {
  consent_id: string;
  kind: "data_processing" | "ai_chat" | "session_recording" | "service_improvement";
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
  email: string | null;
  email_notices: boolean;
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
  | "consent_required"
  | "rate_limited";

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
  feedback?: "up" | "down" | null;
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

export type EscalationReason = "sensitive" | "out_of_scope_medical" | "emergency" | "unclear" | "output_guard";

export interface Escalation {
  escalation_id: string;
  patient_id: string;
  patient_name: string | null;
  reason: EscalationReason;
  status: "open" | "answered" | "closed" | "expired";
  question: string;
  doctor_reply: string | null;
  nudged_at: string | null;
  answered_at: string | null;
  created_at: string;
}

export type Visibility = "doctor_only" | "patient_visible";

export interface PatientCard {
  patient_id: string;
  full_name: string;
  date_of_birth: string | null;
  sex: string | null;
  phone: string | null;
  preferred_language: "ar" | "en";
  first_seen_at: string;
}

export interface DocumentRecord {
  document_id: string;
  patient_id: string;
  doctor_id: string;
  kind: string;
  filename: string;
  mime: string;
  size_bytes: number | null;
  page_count: number | null;
  status: "awaiting_upload" | "uploaded" | "processing" | "indexed" | "failed";
  error: string | null;
  visibility: Visibility;
  ai_description: string | null;
  ai_label: string;
  // the visit it was filed under, when uploaded from that visit's page
  appointment_id?: string | null;
  created_at: string;
}

export interface HistoryRecord {
  entry_id: string;
  doctor_id: string;
  kind: string;
  content: string;
  visibility: Visibility;
  source_type: string | null;
  source_id?: string | null;
  // the visit it was filed under, when written from that visit's page
  appointment_id?: string | null;
  occurred_at: string;
}

export type ConsultationStatus =
  | "recording"
  | "transcribing"
  | "summarizing"
  | "draft_ready"
  | "filing"
  | "approved"
  | "discarded"
  | "failed";

export interface Consultation {
  consultation_id: string;
  patient_id: string;
  appointment_id: string | null;
  status: ConsultationStatus;
  error: string | null;
  part_count: number;
  share_with_patient: boolean;
  started_at: string;
  approved_at: string | null;
  created_at: string;
}

export interface VisitNote {
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
  diagnoses: { name: string; status: "new" | "known" | "suspected" }[];
  medications: { name: string; dose: string; frequency: string; change: "started" | "stopped" | "changed" | "continued" }[];
  allergies: { substance: string; reaction: string }[];
  patient_summary: string;
  uncertain: string[];
}

export interface ConsultationDetail extends Consultation {
  transcript: { start: number; end: number; text: string }[] | null;
  draft: VisitNote | null;
  approved: VisitNote | null;
  model: string | null;
  prompt_version: string | null;
}

export interface MyRecords {
  history: HistoryRecord[];
  documents: DocumentRecord[];
}

export type TimelineItem =
  | ({ type: "appointment"; at: string } & Appointment)
  | ({ type: "history"; at: string } & HistoryRecord)
  | ({ type: "document"; at: string } & DocumentRecord)
  | ({ type: "escalation"; at: string } & Escalation)
  | ({ type: "consultation"; at: string } & Consultation);

export interface Timeline {
  patient: PatientCard;
  timezone: string;
  items: TimelineItem[];
}

/** One session (a visit) in a patient's file, and what was filed under it. */
export interface Session {
  appointment: Appointment;
  // the approved note, and the plain-language summary the patient was given
  summary: { note: HistoryRecord | null; patient: HistoryRecord | null };
  recordings: (Consultation & { transcript: HistoryRecord | null })[];
  documents: DocumentRecord[];
  notes: HistoryRecord[];
  counts: { recordings: number; documents: number; notes: number };
}

/** A patient's file by session, what belongs to none, and the questions still open. */
export interface PatientSessions {
  patient: PatientCard;
  timezone: string;
  sessions: Session[];
  general: { notes: HistoryRecord[]; documents: DocumentRecord[] };
  questions: Escalation[];
}

export interface SessionDetail {
  patient: PatientCard;
  timezone: string;
  session: Session;
}

export interface NextPatient {
  appointment: Appointment | null;
  timezone: string;
  patient?: PatientCard;
  brief?: {
    last_visit: string | null;
    recent_entries: HistoryRecord[];
    open_questions: Escalation[];
    documents: number;
  };
}

export type AssistantEvent =
  | { type: "text"; text: string }
  | { type: "tool"; name: string }
  | { type: "error"; detail: string }
  | { type: "done"; model: string; prompt_version: string };

/**
 * One streamed turn of the doctor's assistant: calls `onEvent` for each
 * server-sent event as it arrives. POST, so EventSource cannot be used.
 */
export async function streamAssistant(
  body: { patient_id?: string | null; messages: { role: "user" | "assistant"; content: string }[] },
  onEvent: (event: AssistantEvent) => void,
): Promise<void> {
  const response = await fetch("/api/doctor/assistant", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(response.status, payload.detail ?? response.statusText, payload.reason);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = frame.split("\n").find((line) => line.startsWith("data: "));
      if (data) onEvent(JSON.parse(data.slice(6)) as AssistantEvent);
    }
    if (done) return;
  }
}

/** Puts a file straight into storage through the upload link, then asks for it to be read. */
export async function uploadDocument(
  patientId: string,
  file: File,
  kind: string,
  appointmentId: string | null = null,
): Promise<DocumentRecord> {
  const started = await call<{ document: DocumentRecord; upload_url: string; content_type: string }>(
    "POST",
    `/api/doctor/patients/${patientId}/documents`,
    {
      kind,
      filename: file.name,
      mime: file.type || "application/octet-stream",
      size_bytes: file.size,
      appointment_id: appointmentId,
    },
  );
  const put = await fetch(started.upload_url, { method: "PUT", body: file, headers: { "Content-Type": started.content_type } });
  if (!put.ok) throw new ApiError(put.status, "the file could not be uploaded");
  return call<DocumentRecord>("POST", `/api/doctor/documents/${started.document.document_id}/uploaded`);
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

/**
 * A streamed chat reply: the server's `delta` events are handed to `onDelta`
 * as the model writes; the `done` event's reply resolves the promise (it is
 * the authority, and replaces what was streamed), an `error` event rejects it.
 * fetch rather than EventSource, which cannot POST.
 */
async function streamReply(path: string, body: FormData | object, onDelta: (text: string) => void): Promise<ChatReply> {
  const form = body instanceof FormData;
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: form ? undefined : { "Content-Type": "application/json" },
    body: form ? body : JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(response.status, typeof payload.detail === "string" ? payload.detail : response.statusText, payload.reason);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const name = block.match(/^event: (.*)$/m)?.[1];
      const data = JSON.parse(block.match(/^data: (.*)$/m)?.[1] ?? "{}");
      if (name === "delta") onDelta(data.text ?? "");
      else if (name === "done") return data as ChatReply;
      else if (name === "error") throw new ApiError(data.status ?? 500, data.detail ?? "error");
    }
  }
  throw new ApiError(502, "the reply stream ended early");
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
  updateProfile: (changes: Partial<Omit<Profile, "patient_id" | "email">>) => call<Profile>("PATCH", "/api/me/profile", changes),
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

  rateReply: (doctorId: string, messageId: string, rating: "up" | "down") =>
    call<void>("PUT", `/api/chat/${doctorId}/messages/${messageId}/feedback`, { rating }),
  chatThread: (doctorId: string) => call<ChatMessage[]>("GET", `/api/chat/${doctorId}/messages`),
  chatSend: (doctorId: string, text: string) => call<ChatReply>("POST", `/api/chat/${doctorId}/messages`, { text }),
  chatVoice: (doctorId: string, audio: Blob) => {
    const form = new FormData();
    form.append("audio", audio, "voice-note");
    return call<ChatReply>("POST", `/api/chat/${doctorId}/voice`, form);
  },
  chatSendStreamed: (doctorId: string, text: string, onDelta: (text: string) => void) =>
    streamReply(`/api/chat/${doctorId}/messages/stream`, { text }, onDelta),
  chatVoiceStreamed: (doctorId: string, audio: Blob, onDelta: (text: string) => void) => {
    const form = new FormData();
    form.append("audio", audio, "voice-note");
    return streamReply(`/api/chat/${doctorId}/voice/stream`, form, onDelta);
  },
  audioUrl: (doctorId: string, messageId: string) => `/api/chat/${doctorId}/messages/${messageId}/audio`,
  consents: () => call<Consent[]>("GET", "/api/me/consents"),
  grantConsent: (kind: "data_processing" | "ai_chat" | "service_improvement", doctorId?: string) =>
    call<Consent>("POST", "/api/me/consents", { kind, doctor_id: doctorId ?? null }),
  revokeConsent: (id: string) => call<void>("POST", `/api/me/consents/${id}/revoke`),
  dialectSuggestion: () => call<{ dialect: SpokenDialect | null }>("GET", "/api/me/dialect-suggestion"),

  notifications: (unreadOnly = false) =>
    call<AppNotification[]>("GET", `/api/notifications?${query({ unread_only: String(unreadOnly) })}`),
  readNotification: (id: string) => call<void>("POST", `/api/notifications/${id}/read`),

  escalations: (status: string[] = ["open"]) =>
    call<Escalation[]>("GET", `/api/doctor/escalations?${status.map((s) => `status=${s}`).join("&")}`),
  replyToEscalation: (id: string, reply: string) =>
    call<Escalation>("POST", `/api/doctor/escalations/${id}/reply`, { reply }),

  patients: () => call<PatientCard[]>("GET", "/api/doctor/patients"),
  timeline: (patientId: string) => call<Timeline>("GET", `/api/doctor/patients/${patientId}/timeline`),
  nextPatient: () => call<NextPatient>("GET", "/api/doctor/next"),
  addNote: (patientId: string, content: string, visibility: Visibility, kind = "note", appointmentId: string | null = null) =>
    call<HistoryRecord>("POST", `/api/doctor/patients/${patientId}/history`, {
      content,
      visibility,
      kind,
      appointment_id: appointmentId,
    }),
  visits: (patientId: string) => call<PatientSessions>("GET", `/api/doctor/patients/${patientId}/visits`),
  visit: (patientId: string, appointmentId: string) =>
    call<SessionDetail>("GET", `/api/doctor/patients/${patientId}/visits/${appointmentId}`),
  setVisibility: (sourceType: "document" | "history", id: string, visibility: Visibility) =>
    call<void>("PATCH", `/api/doctor/records/${sourceType}/${id}/visibility`, { visibility }),
  documentLink: (documentId: string) => call<{ url: string }>("GET", `/api/doctor/documents/${documentId}/download`),

  startConsultation: (patientId: string, evidence: string, appointmentId: string | null = null) =>
    call<Consultation>("POST", `/api/doctor/patients/${patientId}/consultations`, { evidence, appointment_id: appointmentId }),
  consultationPart: (id: string, part: { index: number; mime: string; offset_seconds: number; size_bytes: number }) =>
    call<{ index: number; upload_url: string; content_type: string }>("POST", `/api/doctor/consultations/${id}/parts`, part),
  finishConsultation: (id: string) => call<Consultation>("POST", `/api/doctor/consultations/${id}/finish`),
  consultationsToReview: () => call<Consultation[]>("GET", "/api/doctor/consultations"),
  consultation: (id: string) => call<ConsultationDetail>("GET", `/api/doctor/consultations/${id}`),
  approveConsultation: (id: string, note: VisitNote, shareWithPatient: boolean) =>
    call<Consultation>("POST", `/api/doctor/consultations/${id}/approve`, { note, share_with_patient: shareWithPatient }),
  discardConsultation: (id: string) => call<Consultation>("POST", `/api/doctor/consultations/${id}/discard`),

  myRecords: () => call<MyRecords>("GET", "/api/me/records"),
  myDocumentLink: (documentId: string) => call<{ url: string }>("GET", `/api/me/documents/${documentId}/download`),

  noShow: (appointmentId: string) => call<Appointment>("POST", `/api/doctor/appointments/${appointmentId}/no-show`),

  schedule: (start: Date, end: Date) =>
    call<Schedule>("GET", `/api/doctor/schedule?${query({ start: start.toISOString(), end: end.toISOString() })}`),
};
