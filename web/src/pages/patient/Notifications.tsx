import { useCallback, useEffect, useState } from "react";

import { api, type AppNotification } from "../../api";
import { useI18n } from "../../i18n";
import { clinicClock, clinicDay } from "../../time";

/** Confirmations, reminders and lapsed holds, each with its time at the clinic. */
export default function Notifications({ onRead }: { onRead?: () => void }) {
  const { t, locale } = useI18n();
  const [notices, setNotices] = useState<AppNotification[] | null>(null);

  const load = useCallback(() => {
    api
      .notifications()
      .then(setNotices)
      .catch(() => setNotices([]));
  }, []);

  useEffect(load, [load]);

  async function read(n: AppNotification) {
    await api.readNotification(n.notification_id).catch(() => undefined);
    load();
    onRead?.();
  }

  if (!notices) return <p className="muted">{t("loading")}</p>;

  return (
    <div className="stack">
      <h1>{t("notifications")}</h1>
      {notices.length === 0 && <p className="muted">{t("noNotifications")}</p>}
      {notices.map((n) => (
        <article key={n.notification_id} className={`card appointment ${n.read_at ? "read" : ""}`}>
          <div className="row spread">
            <strong>{t(`notice_${n.kind}`)}</strong>
            {!n.read_at && (
              <button className="secondary" onClick={() => read(n)}>
                {t("markRead")}
              </button>
            )}
          </div>
          <span className="time">
            {clinicDay(n.details.start, n.details.timezone, locale)} · {clinicClock(n.details.start, n.details.timezone, locale)}
          </span>
        </article>
      ))}
    </div>
  );
}
