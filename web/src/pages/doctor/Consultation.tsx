import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError, type ConsultationDetail, type VisitNote } from "../../api";
import { type Key, useI18n } from "../../i18n";

const WORKING = ["recording", "transcribing", "summarizing", "filing"];
const SECTIONS = ["subjective", "objective", "assessment", "plan"] as const;

function clock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  return `${String(m).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

/** Editable rows of one list in the note (diagnoses, medications, allergies). */
function Rows<T extends Record<string, string>>({
  title,
  rows,
  fields,
  blank,
  onChange,
}: {
  title: string;
  rows: T[];
  fields: { key: keyof T & string; label: string; options?: string[] }[];
  blank: T;
  onChange: (rows: T[]) => void;
}) {
  const { t } = useI18n();
  const set = (i: number, key: keyof T, value: string) => onChange(rows.map((r, j) => (j === i ? { ...r, [key]: value } : r)));
  return (
    <fieldset className="stack">
      <legend>{title}</legend>
      {rows.map((row, i) => (
        <div className="row note-row" key={i}>
          {fields.map((f) =>
            f.options ? (
              <select key={f.key} aria-label={f.label} value={row[f.key]} onChange={(e) => set(i, f.key, e.target.value)}>
                {f.options.map((o) => (
                  <option key={o} value={o}>
                    {t(`note_${o}` as Key)}
                  </option>
                ))}
              </select>
            ) : (
              <input dir="auto" key={f.key} aria-label={f.label} placeholder={f.label} value={row[f.key]} onChange={(e) => set(i, f.key, e.target.value)} />
            ),
          )}
          <button className="link" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
            {t("remove")}
          </button>
        </div>
      ))}
      <div>
        <button className="link" onClick={() => onChange([...rows, { ...blank }])}>
          {t("addRow")}
        </button>
      </div>
    </fieldset>
  );
}

/**
 * The draft note of one recorded visit, for the doctor to read against the
 * transcript, correct, and approve; or throw away. Nothing reaches the
 * patient's record before approval, and the patient sees the summary only if shared.
 */
export default function ConsultationPage() {
  const { consultationId } = useParams<{ consultationId: string }>();
  const { t } = useI18n();
  const [consultation, setConsultation] = useState<ConsultationDetail | null>(null);
  const [note, setNote] = useState<VisitNote | null>(null);
  const [share, setShare] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!consultationId) return;
    api
      .consultation(consultationId)
      .then((c) => {
        setConsultation(c);
        setNote((current) => current ?? c.approved ?? c.draft);
      })
      .catch(() => setError(t("error")));
  }, [consultationId, t]);

  useEffect(load, [load]);

  // transcribing and drafting take a while: look again until it settles
  useEffect(() => {
    if (!consultation || !WORKING.includes(consultation.status)) return;
    const timer = setTimeout(load, 2000);
    return () => clearTimeout(timer);
  }, [consultation, load]);

  if (error && !consultation) return <p className="notice error">{error}</p>;
  if (!consultation || !consultationId) return <p className="muted">{t("loading")}</p>;

  async function act(run: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await run();
      load();
    } catch (e) {
      setError(e instanceof ApiError && e.status === 422 ? t("noteIncomplete") : t("error"));
    } finally {
      setBusy(false);
    }
  }

  const editable = consultation.status === "draft_ready" && note;

  return (
    <div className="stack consultation-page">
      <header>
        <Link to={`/doctor/patients/${consultation.patient_id}`} className="small">
          {t("back")}
        </Link>
        <h1>{t("visitNote")}</h1>
        <span className={`badge ${consultation.status}`}>{t(`consultation_${consultation.status}` as Key)}</span>
        {consultation.error && <p className="notice error small">{consultation.error}</p>}
      </header>

      {WORKING.includes(consultation.status) && <p className="muted">{t("consultationWorking")}</p>}

      {editable && (
        <>
          {note.uncertain.length > 0 && (
            <div className="notice warn">
              <strong>{t("checkThese")}</strong>
              <ul>
                {note.uncertain.map((u, i) => (
                  <li key={i} dir="auto">{u}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="muted small">{t("draftDisclaimer")}</p>
          {SECTIONS.map((section) => (
            <label key={section}>
              {t(`soap_${section}` as Key)}
              <textarea dir="auto" value={note[section]} onChange={(e) => setNote({ ...note, [section]: e.target.value })} />
            </label>
          ))}
          <Rows
            title={t("diagnoses")}
            rows={note.diagnoses}
            blank={{ name: "", status: "new" as const }}
            fields={[
              { key: "name", label: t("name") },
              { key: "status", label: t("status"), options: ["new", "known", "suspected"] },
            ]}
            onChange={(diagnoses) => setNote({ ...note, diagnoses })}
          />
          <Rows
            title={t("medications")}
            rows={note.medications}
            blank={{ name: "", dose: "", frequency: "", change: "started" as const }}
            fields={[
              { key: "name", label: t("name") },
              { key: "dose", label: t("dose") },
              { key: "frequency", label: t("frequency") },
              { key: "change", label: t("change"), options: ["started", "stopped", "changed", "continued"] },
            ]}
            onChange={(medications) => setNote({ ...note, medications })}
          />
          <Rows
            title={t("allergies")}
            rows={note.allergies}
            blank={{ substance: "", reaction: "" }}
            fields={[
              { key: "substance", label: t("substance") },
              { key: "reaction", label: t("reaction") },
            ]}
            onChange={(allergies) => setNote({ ...note, allergies })}
          />
          <label>
            {t("patientSummary")}
            <textarea dir="auto" value={note.patient_summary} onChange={(e) => setNote({ ...note, patient_summary: e.target.value })} />
          </label>
          <label className="consent">
            <input type="checkbox" checked={share} onChange={(e) => setShare(e.target.checked)} />
            <span>{t("shareSummary")}</span>
          </label>
          <div className="row">
            <button disabled={busy} onClick={() => act(() => api.approveConsultation(consultationId, note, share))}>
              {t("approveNote")}
            </button>
            <button className="secondary" disabled={busy} onClick={() => act(() => api.discardConsultation(consultationId))}>
              {t("discardRecording")}
            </button>
          </div>
        </>
      )}

      {consultation.status === "failed" && (
        <div className="row">
          <button disabled={busy} onClick={() => act(() => api.finishConsultation(consultationId))}>
            {t("tryAgain")}
          </button>
          <button className="secondary" disabled={busy} onClick={() => act(() => api.discardConsultation(consultationId))}>
            {t("discardRecording")}
          </button>
        </div>
      )}

      {consultation.status === "approved" && consultation.approved && (
        <article className="card stack">
          {SECTIONS.map(
            (section) =>
              consultation.approved![section] && (
                <p key={section} dir="auto">
                  <strong>{t(`soap_${section}` as Key)}:</strong> {consultation.approved![section]}
                </p>
              ),
          )}
          <span className={`badge ${consultation.share_with_patient ? "confirmed" : "held"}`}>
            {consultation.share_with_patient ? t("summaryShared") : t("doctorOnly")}
          </span>
        </article>
      )}

      {error && <p className="notice error small">{error}</p>}

      {consultation.transcript && consultation.transcript.length > 0 && (
        <details className="card">
          <summary>{t("transcript")}</summary>
          <ol className="transcript">
            {consultation.transcript.map((s, i) => (
              <li key={i} dir="auto">
                <span className="muted small">{clock(s.start)}</span> {s.text}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}
