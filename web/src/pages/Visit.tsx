import { ConnectionState, Room, RoomEvent, Track, type RemoteTrack } from "livekit-client";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError, type Appointment } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";

type Joined = { url: string; token: string; role: "doctor" | "patient"; appointment: Appointment };

function readRecording(metadata: string | undefined): { recording: boolean; consultationId?: string } {
  try {
    const parsed = JSON.parse(metadata || "{}");
    return { recording: Boolean(parsed.recording), consultationId: parsed.consultation_id };
  } catch {
    return { recording: false };
  }
}

/**
 * An online visit: the patient and their doctor in one room. Anyone in it
 * sees when it is being recorded; only the doctor starts or stops that,
 * after confirming the patient agreed, and the note then waits for their review.
 */
export default function Visit() {
  const { appointmentId } = useParams<{ appointmentId: string }>();
  const { t, reason } = useI18n();
  const { me } = useAuth();
  const [joined, setJoined] = useState<Joined | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [state, setState] = useState<"lobby" | "connecting" | "in" | "left">("lobby");
  const [micOn, setMicOn] = useState(true);
  const [cameraOn, setCameraOn] = useState(true);
  const [recording, setRecording] = useState<{ recording: boolean; consultationId?: string }>({ recording: false });
  const [agreed, setAgreed] = useState(false);
  const [recorded, setRecorded] = useState<string | null>(null);
  const [others, setOthers] = useState(0);
  const room = useRef<Room | null>(null);
  const localVideo = useRef<HTMLDivElement>(null);
  const remote = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!appointmentId) return;
    api
      .joinVisit(appointmentId)
      .then(setJoined)
      .catch((e) => setRefused(e instanceof ApiError && e.reason ? reason(e.reason) : t("visitUnavailable")));
    return () => {
      room.current?.disconnect();
    };
  }, [appointmentId, reason, t]);

  async function enter() {
    if (!joined) return;
    setState("connecting");
    const r = new Room({ adaptiveStream: true, dynacast: true });
    room.current = r;
    r.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
      const element = track.attach();
      element.dataset.kind = track.kind;
      remote.current?.appendChild(element);
    });
    r.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => track.detach().forEach((el) => el.remove()));
    r.on(RoomEvent.ParticipantConnected, () => setOthers(r.remoteParticipants.size));
    r.on(RoomEvent.ParticipantDisconnected, () => setOthers(r.remoteParticipants.size));
    r.on(RoomEvent.RoomMetadataChanged, (metadata: string) => setRecording(readRecording(metadata)));
    r.on(RoomEvent.Disconnected, () => setState("left"));
    try {
      await r.connect(joined.url, joined.token);
      setRecording(readRecording(r.metadata));
      setOthers(r.remoteParticipants.size);
      await r.localParticipant.setMicrophoneEnabled(true);
      try {
        await r.localParticipant.setCameraEnabled(true);
        const camera = r.localParticipant.getTrackPublication(Track.Source.Camera)?.track;
        if (camera && localVideo.current) localVideo.current.replaceChildren(camera.attach());
      } catch {
        // no camera, or not allowed: the visit goes on by voice
        setCameraOn(false);
      }
      setState(r.state === ConnectionState.Connected ? "in" : "left");
    } catch {
      setRefused(t("visitUnavailable"));
      setState("lobby");
    }
  }

  async function toggleMic() {
    await room.current?.localParticipant.setMicrophoneEnabled(!micOn);
    setMicOn(!micOn);
  }

  async function toggleCamera() {
    await room.current?.localParticipant.setCameraEnabled(!cameraOn);
    setCameraOn(!cameraOn);
  }

  async function startRecording() {
    if (!appointmentId) return;
    const started = await api.startVisitRecording(appointmentId);
    setRecording({ recording: true, consultationId: started.consultation_id });
    setAgreed(false);
  }

  async function stopRecording() {
    if (!recording.consultationId) return;
    await api.stopVisitRecording(recording.consultationId);
    setRecorded(recording.consultationId);
    setRecording({ recording: false });
  }

  if (refused) return <p className="notice warn">{refused}</p>;
  if (!joined) return <p className="muted">{t("loading")}</p>;
  const doctor = joined.role === "doctor" && me?.role === "doctor";

  return (
    <div className="stack visit">
      <h1>{t("onlineVisit")}</h1>
      {recording.recording && (
        <p className="notice error recording-dot" role="status">
          {t("visitRecording")}
        </p>
      )}
      {state === "lobby" && (
        <div className="card stack">
          <p className="muted">{t("visitLobby")}</p>
          <div>
            <button onClick={enter}>{t("joinVisit")}</button>
          </div>
        </div>
      )}
      {state === "connecting" && <p className="muted">{t("connecting")}</p>}
      {state === "left" && <p className="notice info">{t("visitLeft")}</p>}
      <div className="visit-stage" hidden={state !== "in"}>
        <div ref={remote} className="visit-remote" aria-label={t("otherParticipant")}>
          {state === "in" && others === 0 && <p className="muted">{t("waitingForOther")}</p>}
        </div>
        <div ref={localVideo} className="visit-local" aria-label={t("you")} />
      </div>
      {state === "in" && (
        <div className="row">
          <button className="secondary" aria-pressed={!micOn} onClick={toggleMic}>
            {micOn ? t("mute") : t("unmute")}
          </button>
          <button className="secondary" aria-pressed={!cameraOn} onClick={toggleCamera}>
            {cameraOn ? t("cameraOff") : t("cameraOn")}
          </button>
          <button className="danger" onClick={() => room.current?.disconnect()}>
            {t("leaveVisit")}
          </button>
        </div>
      )}
      {doctor && state === "in" && (
        <section className="card stack" aria-label={t("recordVisit")}>
          {recording.recording ? (
            <div>
              <button onClick={stopRecording}>{t("stopVisitRecording")}</button>
            </div>
          ) : (
            <>
              <label className="consent">
                <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
                <span>{t("recordingConsent")}</span>
              </label>
              <div>
                <button disabled={!agreed} onClick={startRecording}>
                  {t("startRecording")}
                </button>
              </div>
            </>
          )}
          {recorded && (
            <Link to={`/doctor/consultations/${recorded}`}>{t("reviewNote")}</Link>
          )}
        </section>
      )}
    </div>
  );
}
