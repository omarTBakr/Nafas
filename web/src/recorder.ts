import { api, ApiError } from "./api";

/** How long each recorded part runs: a dropped connection loses one part at most. */
export const PART_SECONDS = 60;
const UPLOAD_ATTEMPTS = 3;

/** The browser's recorder, in whichever container it supports; MediaRecorder picks when none is named. */
export function recorderType(): string | undefined {
  const preferred = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
  return typeof MediaRecorder !== "undefined" ? preferred.find((t) => MediaRecorder.isTypeSupported?.(t)) : undefined;
}

export interface RecorderProgress {
  seconds: number;
  recorded: number;
  uploaded: number;
  failed: boolean;
}

/**
 * Records a visit in parts of about a minute and uploads each one straight to
 * storage as it ends. Each part is its own recorder, so every file plays and
 * transcribes alone; its offset from the start keeps the transcript in visit time.
 */
export class ChunkedRecorder {
  private stream: MediaStream | null = null;
  private current: MediaRecorder | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private ticker: ReturnType<typeof setInterval> | null = null;
  private startedAt = 0;
  private index = 0;
  private stopping = false;
  private uploads: Promise<void> = Promise.resolve();
  private progress: RecorderProgress = { seconds: 0, recorded: 0, uploaded: 0, failed: false };

  constructor(
    private consultationId: string,
    private onProgress: (progress: RecorderProgress) => void,
    private partSeconds = PART_SECONDS,
  ) {}

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.startedAt = Date.now();
    this.ticker = setInterval(() => this.report({ seconds: Math.floor((Date.now() - this.startedAt) / 1000) }), 1000);
    this.nextPart();
  }

  /** Ends the last part and resolves once every part is uploaded; rejects if one could not be. */
  async stop(): Promise<void> {
    this.stopping = true;
    if (this.timer) clearTimeout(this.timer);
    if (this.ticker) clearInterval(this.ticker);
    await new Promise<void>((resolve) => {
      if (!this.current || this.current.state === "inactive") return resolve();
      this.current.addEventListener("stop", () => resolve(), { once: true });
      this.current.stop();
    });
    this.stream?.getTracks().forEach((track) => track.stop());
    await this.uploads;
    if (this.progress.failed) throw new ApiError(0, "a part of the recording could not be uploaded");
  }

  /** Stops without uploading what is left; the caller discards the consultation. */
  abandon(): void {
    this.stopping = true;
    if (this.timer) clearTimeout(this.timer);
    if (this.ticker) clearInterval(this.ticker);
    if (this.current && this.current.state !== "inactive") {
      this.current.ondataavailable = null;
      this.current.stop();
    }
    this.stream?.getTracks().forEach((track) => track.stop());
  }

  private report(change: Partial<RecorderProgress>) {
    this.progress = { ...this.progress, ...change };
    this.onProgress(this.progress);
  }

  private nextPart() {
    if (!this.stream) return;
    const type = recorderType();
    const recorder = new MediaRecorder(this.stream, type ? { mimeType: type } : undefined);
    const index = this.index++;
    const offset = (Date.now() - this.startedAt) / 1000;
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: recorder.mimeType || type || "audio/webm" });
      if (blob.size > 0) {
        this.report({ recorded: this.progress.recorded + 1 });
        // one upload at a time, in order
        this.uploads = this.uploads.then(() => this.upload(index, offset, blob));
      }
      if (!this.stopping) this.nextPart();
    };
    recorder.start();
    this.current = recorder;
    this.timer = setTimeout(() => recorder.state !== "inactive" && recorder.stop(), this.partSeconds * 1000);
  }

  private async upload(index: number, offset: number, blob: Blob): Promise<void> {
    for (let attempt = 1; attempt <= UPLOAD_ATTEMPTS; attempt++) {
      try {
        const link = await api.consultationPart(this.consultationId, {
          index,
          mime: blob.type,
          offset_seconds: Math.round(offset * 100) / 100,
          size_bytes: blob.size,
        });
        const put = await fetch(link.upload_url, { method: "PUT", body: blob, headers: { "Content-Type": link.content_type } });
        if (!put.ok) throw new ApiError(put.status, "upload refused");
        this.report({ uploaded: this.progress.uploaded + 1 });
        return;
      } catch {
        if (attempt === UPLOAD_ATTEMPTS) this.report({ failed: true });
        else await new Promise((r) => setTimeout(r, 1000 * attempt));
      }
    }
  }
}
