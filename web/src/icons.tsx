/**
 * Small line icons drawn in the text colour, so they follow the theme and
 * read the same on every system (an emoji is drawn differently by each).
 * Decorative: the button that holds one carries the accessible name.
 */

const common = {
  width: 18,
  height: 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  focusable: false,
};

/** Speak into it: record a voice note. */
export function MicIcon() {
  return (
    <svg {...common}>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10v1a7 7 0 0 0 14 0v-1" />
      <path d="M12 18v4" />
      <path d="M8 22h8" />
    </svg>
  );
}

/** Hear it: read a text aloud. */
export function SpeakerIcon() {
  return (
    <svg {...common}>
      <path d="M11 5 6 9H3v6h3l5 4z" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M18.5 5.5a9 9 0 0 1 0 13" />
    </svg>
  );
}

/** Stop what is playing or recording. */
export function StopIcon() {
  return (
    <svg {...common}>
      <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
    </svg>
  );
}
