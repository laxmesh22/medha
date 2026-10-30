// Numbers the dashboard derives from sessions + the active plan. One place, so every page agrees.

import type { CarePlan, Patient, Session } from "./types";

const DAY = 86_400_000;

export type Severity = "good" | "warning" | "serious" | "critical";

export interface Alert {
  severity: Severity;
  label: string;
  detail: string;
}

export interface RomPoint {
  t: number;
  date: string;
  peak: number;
}

export interface PatientSummary {
  patient: Patient;
  age: number | null;
  plan: CarePlan | null;
  sessions: Session[]; // newest first
  lastSession: Session | null;
  daysSinceLast: number | null;
  sessions7: number;
  planned7: number;
  adherence7: number | null; // 0..1, null when there is no plan
  painNow: number | null; // mean pain_after, last 7 days
  painPrev: number | null; // mean pain_after, the 7 days before
  formQuality: number | null; // share of reps accepted, last 7 days
  rom: Record<string, { latest: number | null; first: number | null; series: RomPoint[] }>;
  alerts: Alert[];
  status: Severity;
}

export const SEVERITY_ORDER: Record<Severity, number> = { critical: 3, serious: 2, warning: 1, good: 0 };

export function ageFrom(dob: string | null): number | null {
  if (!dob) return null;
  const d = new Date(dob);
  const now = new Date();
  let a = now.getFullYear() - d.getFullYear();
  if (now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) a--;
  return a;
}

const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

export function plannedPerWeek(plan: CarePlan | null): number {
  if (!plan || !plan.items.length) return 0;
  return Math.max(...plan.items.map((i) => i.times_per_day * i.days_per_week));
}

export function summarize(patient: Patient, plans: CarePlan[], sessions: Session[], now = Date.now()): PatientSummary {
  const plan = plans.find((p) => p.patient_id === patient.id && p.status === "active") ?? null;
  const own = sessions.filter((s) => s.patient_id === patient.id).sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at));
  const in7 = own.filter((s) => now - Date.parse(s.started_at) < 7 * DAY);
  const prev7 = own.filter((s) => now - Date.parse(s.started_at) >= 7 * DAY && now - Date.parse(s.started_at) < 14 * DAY);
  const lastSession = own[0] ?? null;
  const daysSinceLast = lastSession ? calendarDays(lastSession.started_at, now) : null;
  // a patient linked less than a week ago is only expected to have done part of a week
  const weekFrac = Math.min(1, Math.max(1 / 7, (now - Date.parse(patient.consent_at)) / (7 * DAY)));
  const planned7 = Math.round(plannedPerWeek(plan) * weekFrac);
  const adherence7 = plan && planned7 > 0 ? Math.min(1, in7.length / planned7) : null;
  const pain = (ss: Session[]) => mean(ss.map((s) => s.pain_after).filter((v): v is number => v !== null));
  const reps = in7.flatMap((s) => s.exercises).filter((e) => e.reps_rejected !== null);
  const counted = reps.reduce((a, e) => a + e.reps_counted, 0);
  const rejected = reps.reduce((a, e) => a + (e.reps_rejected ?? 0), 0);
  const formQuality = counted + rejected > 0 ? counted / (counted + rejected) : null;

  const rom: PatientSummary["rom"] = {};
  for (const s of [...own].reverse()) {
    for (const e of s.exercises) {
      if (e.peak_deg === null) continue;
      const r = (rom[e.exercise_id] ??= { latest: null, first: null, series: [] });
      const t = Date.parse(s.started_at);
      r.series.push({ t, date: s.started_at, peak: e.peak_deg });
      r.first ??= e.peak_deg;
      r.latest = e.peak_deg;
    }
  }

  // one point per day (the day's best rep): several sessions a day otherwise read as noise
  for (const r of Object.values(rom)) {
    const byDay = new Map<string, RomPoint>();
    for (const pt of r.series) {
      const d = new Date(pt.t);
      const key = d.toDateString();
      const cur = byDay.get(key);
      if (!cur || pt.peak > cur.peak) byDay.set(key, { t: new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12).getTime(), date: pt.date, peak: pt.peak });
    }
    r.series = [...byDay.values()].sort((x, y) => x.t - y.t);
  }

  const alerts: Alert[] = [];
  const painNow = pain(in7);
  const painPrev = pain(prev7);
  const maxPain = Math.max(-1, ...in7.slice(0, 6).map((s) => s.pain_after ?? -1));
  if (maxPain >= 7) alerts.push({ severity: "critical", label: "High pain", detail: `Pain ${maxPain}/10 after a recent session` });
  if (painNow !== null && painPrev !== null && painNow - painPrev >= 1.5)
    alerts.push({ severity: "serious", label: "Pain rising", detail: `Avg pain ${painPrev.toFixed(1)} → ${painNow.toFixed(1)} this week` });
  if (plan && daysSinceLast === null) alerts.push({ severity: "warning", label: "Not started", detail: "No sessions logged yet" });
  if (daysSinceLast !== null && daysSinceLast >= 3) alerts.push({ severity: "warning", label: "Missed sessions", detail: `Last session ${daysSinceLast} days ago` });
  if (formQuality !== null && formQuality < 0.75)
    alerts.push({ severity: "warning", label: "Form issues", detail: `${Math.round((1 - formQuality) * 100)}% of reps rejected this week` });
  const status = alerts.reduce<Severity>((w, a) => (SEVERITY_ORDER[a.severity] > SEVERITY_ORDER[w] ? a.severity : w), "good");
  return { patient, age: ageFrom(patient.date_of_birth), plan, sessions: own, lastSession, daysSinceLast,
    sessions7: in7.length, planned7, adherence7, painNow, painPrev, formQuality, rom, alerts, status };
}

export const FLAG_LABELS: Record<string, string> = {
  TRUNK_LEAN_SAGITTAL: "Leaned forward / back",
  TRUNK_LEAN_LATERAL: "Leaned sideways",
  APPARENT_TRUE_GAP: "Body lean added range",
  ELBOW_DRIFT: "Elbow left the side",
  SHRUG: "Shrugged the shoulder",
  TOO_FAST: "Moved too fast",
};

/** Calendar days between two moments (yesterday 23:00 -> today 08:00 is 1 day). */
export function calendarDays(iso: string, now = Date.now()): number {
  const a = new Date(iso);
  const b = new Date(now);
  return Math.round((Date.UTC(b.getFullYear(), b.getMonth(), b.getDate()) - Date.UTC(a.getFullYear(), a.getMonth(), a.getDate())) / DAY);
}

export function relativeDay(iso: string, now = Date.now()): string {
  const d = calendarDays(iso, now);
  if (d <= 0) return "Today";
  if (d === 1) return "Yesterday";
  return `${d} days ago`;
}

export const fmtDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
export const fmtDateTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
export const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);
export const deg = (v: number | null) => (v === null ? "—" : `${Math.round(v)}°`);
export const initials = (name: string) => name.replace(/^Dr\.?\s+/i, "").split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
