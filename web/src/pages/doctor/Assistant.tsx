import { useEffect, useRef, useState } from "react";

import { api, ApiError, streamAssistant } from "../../api";
import { type Key, useI18n } from "../../i18n";
import { MicIcon, SpeakerIcon, StopIcon } from "../../icons";
import Markdown from "../../Markdown";
import { recorderType } from "../../recorder";
import { DIALECTS, Reader, type SpeechDialect } from "../../speech";

interface Line {
  role: "user" | "assistant";
  content: string;
}

const SETTINGS_KEY = "nafas.assistantVoice";

interface VoiceSettings {
  // read each answer aloud as soon as it is finished
  auto: boolean;
  dialect: SpeechDialect;
}

function savedVoice(): VoiceSettings {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "{}");
    return { auto: saved.auto === true, dialect: DIALECTS.includes(saved.dialect) ? saved.dialect : "eg" };
  } catch {
    return { auto: false, dialect: "eg" };
  }
}

/** The doctor's assistant: answers stream in as they are written, and can be read aloud; for one patient when `patientId` is given. */
export default function Assistant({ patientId }: { patientId?: string }) {
  const { t, reason } = useI18n();
  const [lines, setLines] = useState<Line[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voice, setVoice] = useState<VoiceSettings>(savedVoice);
  // the answer being read aloud, by its place in the conversation
  const [speaking, setSpeaking] = useState<number | null>(null);
  // why nothing could be heard, when that happens
  const [voiceProblem, setVoiceProblem] = useState<string | null>(null);
  const reader = useRef(new Reader());
  // dictating a question: recording it, then turning it into text for the box
  const [dictation, setDictation] = useState<"idle" | "recording" | "transcribing">("idle");
  const recorder = useRef<MediaRecorder | null>(null);
  const input = useRef<HTMLInputElement>(null);

  // leaving the page stops the voice and the microphone
  useEffect(() => {
    const current = reader.current;
    return () => {
      current.stop();
      recorder.current?.stream.getTracks().forEach((track) => track.stop());
    };
  }, []);

  async function startDictation() {
    setError(null);
    reader.current.stop();
    setSpeaking(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError(t("micDenied"));
      return;
    }
    const type = recorderType();
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    rec.ondataavailable = (event) => chunks.push(event.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop());
      recorder.current = null;
      const audio = new Blob(chunks, { type: rec.mimeType || type || "audio/webm" });
      if (audio.size === 0) return setDictation("idle");
      setDictation("transcribing");
      try {
        const { text } = await api.transcribeDictation(audio);
        // the doctor reads it over, and may add to it, before asking
        if (text) setDraft((current) => (current.trim() ? `${current.trim()} ${text}` : text));
        else setError(t("dictationEmpty"));
      } catch {
        setError(t("dictationFailed"));
      } finally {
        setDictation("idle");
        input.current?.focus();
      }
    };
    recorder.current = rec;
    rec.start();
    setDictation("recording");
  }

  function stopDictation() {
    recorder.current?.stop();
  }

  function changeVoice(next: VoiceSettings) {
    setVoice(next);
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(next));
    } catch {
      // a remembered choice is a convenience; the voice still works without it
    }
  }

  function readAloud(index: number, content: string) {
    if (speaking === index) {
      reader.current.stop();
      setSpeaking(null);
      return;
    }
    setSpeaking(index);
    setVoiceProblem(null);
    void reader.current
      .read(content, {
        dialect: voice.dialect,
        onEnd: () => setSpeaking((now) => (now === index ? null : now)),
      })
      .then((outcome) => {
        if (outcome === "no_voice") setVoiceProblem(t("noBrowserVoice"));
        else if (outcome === "unavailable") setVoiceProblem(t("voiceUnavailable"));
      });
  }

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    const question = draft.trim();
    if (!question || busy) return;
    const history: Line[] = [...lines, { role: "user", content: question }];
    setLines([...history, { role: "assistant", content: "" }]);
    setDraft("");
    setBusy(true);
    setError(null);
    reader.current.stop();
    setSpeaking(null);
    let answer = "";
    let failed = false;
    try {
      await streamAssistant({ patient_id: patientId ?? null, messages: history }, (event) => {
        if (event.type === "text") {
          setReading(false);
          answer += event.text;
          setLines((current) => {
            const next = [...current];
            next[next.length - 1] = { role: "assistant", content: next[next.length - 1].content + event.text };
            return next;
          });
        } else if (event.type === "tool") setReading(true);
        else if (event.type === "error") {
          failed = true;
          setError(event.detail);
        }
      });
    } catch (e) {
      failed = true;
      setError(e instanceof ApiError && e.reason ? reason(e.reason) : t("error"));
      setLines(history.slice(0, -1));
      setDraft(question);
    } finally {
      setBusy(false);
      setReading(false);
    }
    if (voice.auto && !failed && answer.trim()) readAloud(history.length, answer);
  }

  return (
    <section className="card stack chat" aria-label={t("assistant")}>
      <h3 style={{ marginBlock: 0 }}>{t("assistant")}</h3>
      <p className="muted small">{patientId ? t("assistantHint") : t("assistantGeneral")}</p>
      <div className="row voice-settings">
        <label className="consent">
          <input type="checkbox" checked={voice.auto} onChange={(e) => changeVoice({ ...voice, auto: e.target.checked })} />
          <span>{t("readAnswersAloud")}</span>
        </label>
        <select
          aria-label={t("voiceDialect")}
          value={voice.dialect}
          onChange={(e) => changeVoice({ ...voice, dialect: e.target.value as SpeechDialect })}
        >
          {DIALECTS.map((d) => (
            <option key={d} value={d}>
              {t(`dialect_${d}` as Key)}
            </option>
          ))}
        </select>
      </div>
      <div className="messages" role="log" aria-live="polite">
        {lines.map((line, i) => (
          <div key={i} className={`bubble-row ${line.role === "user" ? "patient" : "assistant"}`}>
            <div className={`bubble ${line.role === "user" ? "patient" : "assistant"}`}>
              {line.role === "assistant" ? <Markdown text={line.content} /> : <p>{line.content}</p>}
              {line.role === "assistant" && line.content && !(busy && i === lines.length - 1) && (
                <button
                  type="button"
                  className="link icon-button"
                  aria-pressed={speaking === i}
                  aria-label={speaking === i ? t("stopReading") : t("readAloud")}
                  title={speaking === i ? t("stopReading") : t("readAloud")}
                  onClick={() => readAloud(i, line.content)}
                >
                  {speaking === i ? <StopIcon /> : <SpeakerIcon />}
                </button>
              )}
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
      {voiceProblem && (
        <p className="notice info small" role="status">
          {voiceProblem}
        </p>
      )}
      <form className="row composer" onSubmit={ask}>
        <input
          ref={input}
          aria-label={t("askAssistant")}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          maxLength={20000}
          disabled={dictation === "transcribing"}
        />
        <button disabled={busy || dictation !== "idle" || !draft.trim()}>{t("askAssistant")}</button>
        {dictation === "recording" ? (
          <button type="button" className="danger icon-text" onClick={stopDictation}>
            <StopIcon />
            {t("stopDictating")}
          </button>
        ) : (
          <button
            type="button"
            className="secondary icon-button"
            onClick={startDictation}
            disabled={busy || dictation === "transcribing"}
            aria-label={t("dictate")}
            title={t("dictate")}
          >
            <MicIcon />
          </button>
        )}
      </form>
      {dictation === "recording" && (
        <p className="muted small recording-dot" aria-live="polite">
          {t("recording")}
        </p>
      )}
      {dictation === "transcribing" && (
        <p className="muted small" aria-live="polite">
          {t("transcribingDictation")}
        </p>
      )}
    </section>
  );
}
