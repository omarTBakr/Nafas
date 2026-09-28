import { useState } from "react";

import { ApiError, streamAssistant } from "../../api";
import { useI18n } from "../../i18n";
import Markdown from "../../Markdown";

interface Line {
  role: "user" | "assistant";
  content: string;
}

/** The doctor's assistant: answers stream in as they are written; for one patient when `patientId` is given. */
export default function Assistant({ patientId }: { patientId?: string }) {
  const { t, reason } = useI18n();
  const [lines, setLines] = useState<Line[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    const question = draft.trim();
    if (!question || busy) return;
    const history: Line[] = [...lines, { role: "user", content: question }];
    setLines([...history, { role: "assistant", content: "" }]);
    setDraft("");
    setBusy(true);
    setError(null);
    try {
      await streamAssistant({ patient_id: patientId ?? null, messages: history }, (event) => {
        if (event.type === "text") {
          setReading(false);
          setLines((current) => {
            const next = [...current];
            next[next.length - 1] = { role: "assistant", content: next[next.length - 1].content + event.text };
            return next;
          });
        } else if (event.type === "tool") setReading(true);
        else if (event.type === "error") setError(event.detail);
      });
    } catch (e) {
      setError(e instanceof ApiError && e.reason ? reason(e.reason) : t("error"));
      setLines(history.slice(0, -1));
      setDraft(question);
    } finally {
      setBusy(false);
      setReading(false);
    }
  }

  return (
    <section className="card stack chat" aria-label={t("assistant")}>
      <h3 style={{ marginBlock: 0 }}>{t("assistant")}</h3>
      <p className="muted small">{patientId ? t("assistantHint") : t("assistantGeneral")}</p>
      <div className="messages" role="log" aria-live="polite">
        {lines.map((line, i) => (
          <div key={i} className={`bubble-row ${line.role === "user" ? "patient" : "assistant"}`}>
            <div className={`bubble ${line.role === "user" ? "patient" : "assistant"}`}>
              {line.role === "assistant" ? <Markdown text={line.content} /> : <p>{line.content}</p>}
            </div>
          </div>
        ))}
        {reading && <p className="muted small typing">{t("readingRecord")}</p>}
      </div>
      {error && (
        <p className="notice warn" role="alert">
          {error}
        </p>
      )}
      <form className="row composer" onSubmit={ask}>
        <input aria-label={t("askAssistant")} value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={20000} />
        <button disabled={busy || !draft.trim()}>{t("askAssistant")}</button>
      </form>
    </section>
  );
}
