// Auri brand mark (brand sheet, 28 Oct 2026): a goniometer drawn as a compass, i.e. a ring at the pivot, two legs
// and a measuring arc with ticks, on a rounded tile. Deep Teal #0A4A4F, Off-White #F5F2EA.
// public/favicon.svg and the PNG icons are this same drawing.
export const BRAND = { teal: "#0a4a4f", offwhite: "#f5f2ea" };

/** The mark on its tile. `tone="teal"`: teal tile, light mark (primary); `"light"`: light tile, teal mark (on teal). */
export function AuriMark({ size = 36, tone = "teal", detail = size >= 24 }: { size?: number; tone?: "teal" | "light"; detail?: boolean }) {
  const tile = tone === "teal" ? BRAND.teal : BRAND.offwhite;
  const ink = tone === "teal" ? BRAND.offwhite : BRAND.teal;
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden style={{ flex: "0 0 auto", display: "block" }}>
      <rect width="64" height="64" rx="15" fill={tile} />
      <g stroke={ink} strokeLinecap="round" fill="none">
        <path d="M30.3 20.2 L19.5 50 M33.7 20.2 L44.5 50" strokeWidth="4.2" />
        <circle cx="32" cy="15" r="4.6" strokeWidth="3.8" />
        <path d="M24.6 36.6 Q32 39.6 39.6 35.6" strokeWidth="2.6" />
        {detail ? <path d="M26.6 40.4 L26.1 42.4 M29.2 41.2 L29 43.3 M31.8 41.5 L31.8 43.6 M34.4 41.2 L34.7 43.3 M37 40.4 L37.6 42.3" strokeWidth="1.5" /> : null}
      </g>
      <circle cx="39.6" cy="35.6" r="2.6" fill={ink} />
    </svg>
  );
}

/** Mark + wide-tracked AURI wordmark, optionally with a line under it. */
export function AuriLockup({ size = 36, tone = "teal", sub }: { size?: number; tone?: "teal" | "light"; sub?: string }) {
  return (
    <span className="lockup">
      <AuriMark size={size} tone={tone} />
      <span>
        <span className="wordmark" style={{ fontSize: size * 0.56 }}>AURI</span>
        {sub ? <span className="lockup-sub">{sub}</span> : null}
      </span>
    </span>
  );
}
