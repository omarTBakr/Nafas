/**
 * Reading the assistant's answers aloud to the doctor, with two voices:
 * an Arabic answer in Nafas's dialect voice (the tts service, through
 * /api/doctor/speak), anything else in the browser's own voice. When the
 * dialect voice is unavailable the browser reads the rest instead, so a
 * press of the button is never met with silence.
 */

export type SpeechDialect = "eg" | "sa" | "ma" | "bh" | "sd" | "iq" | "lb" | "sy" | "ly" | "ps" | "tn" | "dz" | "ye";
export const DIALECTS: SpeechDialect[] = ["eg", "sa", "ma", "bh", "sd", "iq", "lb", "sy", "ly", "ps", "tn", "dz", "ye"];

// under the tts service's 600-character limit, with room to spare
const MAX_PASSAGE = 450;
// an answer this Arabic goes to the dialect voice; one with more English in it, to the browser's
const ARABIC_SHARE = 0.85;

/** What a listener should hear of a Markdown answer: the words, without the markup. */
export function plainText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+[.)]\s+/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/^\s*\|?[\s:-]+\|[\s|:-]*$/gm, "")
    .replace(/\|/g, "، ")
    .replace(/(\*\*|__|\*|_|~~)/g, "")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{2,}/g, "\n")
    .trim();
}

/** The share of an answer's letters that are Arabic. */
export function arabicShare(text: string): number {
  const arabic = text.match(/[؀-ۿ]/g)?.length ?? 0;
  const latin = text.match(/[A-Za-z]/g)?.length ?? 0;
  return arabic + latin === 0 ? 0 : arabic / (arabic + latin);
}

export function voiceFor(text: string): "dialect" | "browser" {
  return arabicShare(text) >= ARABIC_SHARE ? "dialect" : "browser";
}

/** The text in passages the voice can take in one go, split where a sentence or line ends. */
export function passages(text: string, max = MAX_PASSAGE): string[] {
  const sentences = text.split(/(?<=[.!?؟؛\n])\s+/).filter((s) => s.trim());
  const out: string[] = [];
  let current = "";
  for (const sentence of sentences) {
    // a single sentence longer than a passage is cut at its spaces
    const pieces = sentence.length <= max ? [sentence] : (sentence.match(new RegExp(`.{1,${max}}(\\s|$)`, "g")) ?? [sentence]);
    for (const piece of pieces) {
      if (current && current.length + piece.length + 1 > max) {
        out.push(current.trim());
        current = "";
      }
      current += (current ? " " : "") + piece;
    }
  }
  if (current.trim()) out.push(current.trim());
  return out;
}

export type ReadOutcome = "done" | "stopped" | "no_voice" | "unavailable";

/**
 * The browser's installed voices. Chrome fills the list a moment after the
 * page loads, so an empty one is given a short while to arrive.
 */
export function browserVoices(waitMs = 1000): Promise<SpeechSynthesisVoice[]> {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return Promise.resolve([]);
  const synth = window.speechSynthesis;
  const now = synth.getVoices();
  if (now.length || waitMs <= 0) return Promise.resolve(now);
  return new Promise((resolve) => {
    const done = () => {
      synth.removeEventListener?.("voiceschanged", done);
      resolve(synth.getVoices());
    };
    synth.addEventListener?.("voiceschanged", done);
    setTimeout(done, waitMs);
  });
}

export interface SpeakOptions {
  dialect: SpeechDialect;
  voice?: "female" | "male" | null;
  onEnd?: () => void;
}

/**
 * Reads one answer at a time: starting another stops the first. The next
 * passage is fetched while the current one plays, so the dialect voice runs
 * on without long gaps.
 */
export class Reader {
  private run = 0;
  private audio: HTMLAudioElement | null = null;

  get speaking(): boolean {
    return this.run % 2 === 1;
  }

  stop(): void {
    if (this.speaking) this.run += 1;
    this.audio?.pause();
    this.audio = null;
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }

  /**
   * Reads one answer; resolves with how it went. "no_voice": nothing could
   * read it (English, and the browser has no voice installed); "unavailable":
   * the dialect voice failed and the browser has none to take over.
   */
  async read(markdown: string, options: SpeakOptions): Promise<ReadOutcome> {
    this.stop();
    this.run += 1;
    const mine = this.run;
    const text = plainText(markdown);
    const parts = passages(text);
    const arabic = arabicShare(text) > 0.5;
    try {
      const browserCan = (await browserVoices()).length > 0;
      // a mostly Arabic answer with a few English words: the dialect voice, when the browser has none
      const engine = voiceFor(text) === "dialect" || (arabic && !browserCan) ? "dialect" : "browser";
      if (engine === "browser") {
        if (!browserCan) return "no_voice";
        await this.browser(parts, arabic ? "ar" : "en", mine);
        return mine === this.run ? "done" : "stopped";
      }
      const rest = await this.dialect(parts, options, mine);
      if (mine !== this.run) return "stopped";
      if (!rest.length) return "done";
      if (!browserCan) return "unavailable";
      await this.browser(rest, "ar", mine);
      return mine === this.run ? "done" : "stopped";
    } finally {
      if (mine === this.run) {
        this.run += 1;
        options.onEnd?.();
      }
    }
  }

  /** Plays the passages in the dialect voice; what it could not play is handed back for the browser to read. */
  private async dialect(parts: string[], options: SpeakOptions, mine: number): Promise<string[]> {
    const fetchPart = (text: string) =>
      fetch("/api/doctor/speak", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, dialect: options.dialect, voice: options.voice ?? null }),
      }).then((r) => (r.ok ? r.blob() : Promise.reject(new Error(`speak ${r.status}`))));

    let next: Promise<Blob> | null = parts.length ? fetchPart(parts[0]) : null;
    for (let i = 0; i < parts.length; i++) {
      if (mine !== this.run) return [];
      let blob: Blob;
      try {
        blob = await next!;
      } catch {
        return parts.slice(i);
      }
      next = i + 1 < parts.length ? fetchPart(parts[i + 1]) : null;
      // a rejected prefetch is handled when its turn comes
      next?.catch(() => undefined);
      if (mine !== this.run) return [];
      await this.play(blob);
    }
    return [];
  }

  private play(blob: Blob): Promise<void> {
    return new Promise((resolve) => {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      this.audio = audio;
      const done = () => {
        URL.revokeObjectURL(url);
        resolve();
      };
      audio.onended = done;
      audio.onerror = done;
      audio.onpause = done;
      audio.play().catch(done);
    });
  }

  private browser(parts: string[], language: "ar" | "en", mine: number): Promise<void> {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return Promise.resolve();
    const synth = window.speechSynthesis;
    const lang = language === "ar" ? "ar-EG" : "en-US";
    const voice = synth.getVoices().find((v) => v.lang.startsWith(language)) ?? null;
    return parts.reduce<Promise<void>>(
      (chain, part) =>
        chain.then(
          () =>
            new Promise((resolve) => {
              if (mine !== this.run) return resolve();
              const utterance = new SpeechSynthesisUtterance(part);
              utterance.lang = lang;
              if (voice) utterance.voice = voice;
              utterance.onend = () => resolve();
              utterance.onerror = () => resolve();
              synth.speak(utterance);
            }),
        ),
      Promise.resolve(),
    );
  }
}
