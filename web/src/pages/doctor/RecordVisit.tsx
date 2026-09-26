import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../../api";
import { useI18n } from "../../i18n";
import { ChunkedRecorder, type RecorderProgress } from "../../recorder";

function clock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/**
 * Records an in-person visit. The doctor confirms the patient agreed to this
 * recording (asked afresh every time), then records; parts upload as they
 * end. Stopping sends it to be transcribed and drafted for review.
 */
export default function RecordVisit({ patientId, onChange }: { patientId: string; onChange: () => void }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [agreed, setAgreed] = useState(false);
  const [consultationId, setConsultationId] = useState<string | null>(null);
  const [progress, setProgress] = useState<RecorderProgress | null>(null);
  const [state, setState] = useState<"idle" | "recording" | "sending">("idle");
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<ChunkedRecorder | null>(null);

  // leaving the page mid-recording stops the microphone
  useEffect(() => () => recorder.current?.abandon(), []);

  async function start() {
    setError(null);
    try {
      const consultation = await api.startConsultation(patientId, "verbal, in the room");
      const rec = new ChunkedRecorder(consultation.consultation_id, setProgress);
      await rec.start();
      recorder.current = rec;
      setConsultationId(consultation.consultation_id);
      setState("recording");
    } catch {
      setError(t("micOrStartFailed"));
    }
  }

  async function stop() {
    if (!recorder.current || !consultationId) return;
    setState("sending");
    try {
      await recorder.current.stop();
      await api.finishConsultation(consultationId);
      navigate(`/doctor/consultations/${consultationId}`);
    } catch {
      setError(t("recordingUploadFailed"));
      setState("recording");
    }
  }

  async function discard() {
    recorder.current?.abandon();
    if (consultationId) await api.discardConsultation(consultationId).catch(() => undefined);
    recorder.current = null;
    setConsultationId(null);
    setProgress(null);
    setAgreed(false);
    setState("idle");
    onChange();
  }

  return (
    <section className="card stack record-visit" aria-label={t("recordVisit")}>
      <strong>{t("recordVisit")}</strong>
      {state === "idle" ? (
        <>
          <label className="consent">
            <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
            <span>{t("recordingConsent")}</span>
          </label>
          <div>
            <button disabled={!agreed} onClick={start}>
              {t("startRecording")}
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="row spread">
            <span className="recording-dot" aria-live="polite">
              {state === "sending" ? t("sendingRecording") : `${t("recordingNow")} ${clock(progress?.seconds ?? 0)}`}
            </span>
            <span className="muted small">
              {t("partsUploaded")} {progress?.uploaded ?? 0}/{progress?.recorded ?? 0}
            </span>
          </div>
          <div className="row">
            <button onClick={stop} disabled={state === "sending"}>
              {t("finishRecording")}
            </button>
            <button className="secondary" onClick={discard} disabled={state === "sending"}>
              {t("discardRecording")}
            </button>
          </div>
        </>
      )}
      {error && <p className="notice error small">{error}</p>}
    </section>
  );
}
