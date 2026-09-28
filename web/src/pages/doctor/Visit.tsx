import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type SessionDetail } from "../../api";
import { useI18n } from "../../i18n";
import { reading, SessionCard } from "./sessions";

/** One session on its own page, opened: a link straight to a visit. */
export default function Visit() {
  const { patientId, appointmentId } = useParams<{ patientId: string; appointmentId: string }>();
  const { t } = useI18n();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [failed, setFailed] = useState<"missing" | "error" | null>(null);

  const load = useCallback(() => {
    if (!patientId || !appointmentId) return;
    api
      .visit(patientId, appointmentId)
      .then(setDetail)
      .catch((e) => setFailed(e?.status === 404 ? "missing" : "error"));
  }, [patientId, appointmentId]);

  useEffect(load, [load]);

  // a document being read changes status on its own: look again until it settles
  useEffect(() => {
    if (!detail || !reading(detail.session.documents)) return;
    const timer = setTimeout(load, 2000);
    return () => clearTimeout(timer);
  }, [detail, load]);

  if (failed) return <p className="notice error">{failed === "missing" ? t("visitNotFound") : t("error")}</p>;
  if (!detail || !patientId) return <p className="muted">{t("loading")}</p>;

  return (
    <div className="narrow stack">
      <header>
        <Link to={`/doctor/patients/${patientId}#session-${appointmentId}`} className="small">
          {t("back")}
        </Link>
        <h1>{detail.patient.full_name}</h1>
      </header>
      <SessionCard patientId={patientId} session={detail.session} tz={detail.timezone} reload={load} open />
    </div>
  );
}
