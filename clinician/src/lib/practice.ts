// The form asks for the year practice started. The database column is still years_experience
// (an integer 0–70). A calendar year is converted here so a value like 2017 is never sent to
// the check constraint.

export function yearsForStorage(typed: string, now = new Date().getFullYear()): string {
  const t = typed.trim();
  if (!t) return "";
  const n = Number(t);
  if (!Number.isFinite(n)) return "";
  const years = n >= 1950 && n <= now ? now - n : n;
  return String(Math.min(70, Math.max(0, Math.round(years))));
}

/** Year practice started, from the stored year-count. "—" when it was not given. */
export function practisingSince(stored: number | null | undefined, now = new Date().getFullYear()): string {
  if (stored === null || stored === undefined || Number.isNaN(Number(stored))) return "—";
  return String(now - stored);
}
