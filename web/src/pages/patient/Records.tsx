import { useEffect, useState } from "react";

import { api, type Doctor, type MyRecords } from "../../api";
import { type Key, useI18n } from "../../i18n";

/** What the patient's doctors shared with them: notes, visit summaries and documents, newest first. */
export default function Records() {
  const { t, locale, lang } = useI18n();
  const [records, setRecords] = useState<MyRecords | null>(null);
  const [doctors, setDoctors] = useState<Record<string, string>>({});
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api
      .myRecords()
      .then(setRecords)
      .catch(() => setFailed(true));
    api
      .doctors()
      .then((all: Doctor[]) => setDoctors(Object.fromEntries(all.map((d) => [d.doctor_id, lang === "ar" ? d.full_name_ar : d.full_name_en]))))
      .catch(() => undefined);
  }, [lang]);

  if (failed) return <p className="notice error">{t("error")}</p>;
  if (!records) return <p className="muted">{t("loading")}</p>;

  const day = (at: string) => new Date(at).toLocaleDateString(locale, { day: "numeric", month: "long", year: "numeric" });
  const empty = records.history.length === 0 && records.documents.length === 0;

  return (
    <div className="stack">
      <h1>{t("myRecords")}</h1>
      <p className="muted">{t("myRecordsHint")}</p>
      {empty && <p className="muted">{t("nothingShared")}</p>}
      {records.history.map((entry) => (
        <article key={entry.entry_id} className="card stack">
          <div className="row spread">
            <strong>{t(`kind_${entry.kind}` as Key)}</strong>
            <span className="muted small">
              {doctors[entry.doctor_id] ?? ""} · {day(entry.occurred_at)}
            </span>
          </div>
          <p className="question" dir="auto">{entry.content}</p>
        </article>
      ))}
      {records.documents.length > 0 && <h2>{t("documents")}</h2>}
      {records.documents.map((d) => (
        <article key={d.document_id} className="card row spread">
          <span>
            {d.filename} <span className="muted small">· {doctors[d.doctor_id] ?? ""} · {day(d.created_at)}</span>
          </span>
          <button
            className="link"
            onClick={async () => {
              const { url } = await api.myDocumentLink(d.document_id);
              window.open(url, "_blank", "noopener");
            }}
          >
            {t("open")}
          </button>
        </article>
      ))}
    </div>
  );
}
