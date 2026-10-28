// Demo store: used whenever VITE_SUPABASE_URL is not set, so the dashboard can be shown without a backend.
// All people are fictional. Sessions are generated deterministically relative to "now"; plan edits and the
// referral code persist in this browser (localStorage) so a demo can show prescribing.

import type { Api, CarePlan, Clinician, ClinicianInput, Exercise, Patient, PlanItem, Session, SessionExercise } from "./types";

export const EXERCISES: Exercise[] = [
  { id: "flexion", name: "Forward raise (flexion)", metric: "elevation", description: "Raise the straight arm forward and up, thumb leading.", default_sets: 2, default_reps: 10, default_hold: 3 },
  { id: "abduction", name: "Side raise (abduction)", metric: "elevation", description: "Raise the straight arm out to the side, palm down.", default_sets: 2, default_reps: 10, default_hold: 3 },
  { id: "external_rotation", name: "Outward rotation", metric: "rotation", description: "Elbow at the side, bent 90°; swing the forearm out.", default_sets: 2, default_reps: 10, default_hold: 3 },
  { id: "internal_rotation", name: "Inward rotation", metric: "rotation", description: "Elbow at the side, bent 90°; swing the forearm in.", default_sets: 2, default_reps: 10, default_hold: 3 },
  { id: "pendulum", name: "Pendulum", metric: "elevation", description: "Lean forward, let the arm hang and swing it in small circles.", default_sets: 2, default_reps: 10, default_hold: 0 },
];

const DAY = 86_400_000;
const STORE_KEY = "pb-clinician-demo-v1";

function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const isoDaysAgo = (d: number, hour = 9) => {
  const t = new Date(Date.now() - d * DAY);
  t.setHours(hour, 0, 0, 0);
  return t.toISOString();
};

interface Profile {
  patient: Omit<Patient, "created_at" | "consent_at">;
  linkedDaysAgo: number;
  /** adherence probability per planned day */
  adherence: number;
  /** degrees gained per week at peak, per exercise */
  start: Record<string, number>;
  gain: Record<string, number>;
  pain: [number, number]; // pain_after at start -> now
  skipLastDays?: number;
  painSpikeDays?: number; // pain rises over the last N days
  lean?: boolean; // many rejected reps with trunk lean
  plan?: PlanItem[];
}

const item = (exercise_id: string, rom_target_deg: number | null, extra: Partial<PlanItem> = {}): PlanItem => ({
  exercise_id, sets: 2, reps: 10, hold_s: exercise_id === "pendulum" ? 0 : 3, times_per_day: 2, days_per_week: 7,
  rom_target_deg, pain_stop: 6, notes: null, ...extra,
});

const STD_PLAN = [item("flexion", 140), item("abduction", 110), item("external_rotation", 45), item("pendulum", null, { times_per_day: 3 })];

const PROFILES: Profile[] = [
  {
    patient: { id: "p-meera", full_name: "Meera Kulkarni", date_of_birth: "1972-03-14", sex: "female", phone: "+91 98201 41122",
      affected_side: "right", dominant_side: "right", diagnosis: "Adhesive capsulitis, freezing phase", symptom_onset: "2026-06-02",
      conditions: ["Type 2 diabetes"], medications: "Metformin 500 mg BD", notes: "Night pain, sleeps on the left side." },
    linkedDaysAgo: 31, adherence: 0.9, start: { flexion: 92, abduction: 70, external_rotation: 18, pendulum: 25 },
    gain: { flexion: 6.5, abduction: 5, external_rotation: 3.2, pendulum: 1 }, pain: [6, 3], plan: STD_PLAN,
  },
  {
    patient: { id: "p-rajesh", full_name: "Rajesh Iyer", date_of_birth: "1965-11-02", sex: "male", phone: "+91 98451 22870",
      affected_side: "left", dominant_side: "right", diagnosis: "Adhesive capsulitis, frozen phase", symptom_onset: "2026-04-20",
      conditions: ["Hypothyroidism"], medications: "Levothyroxine 50 mcg OD", notes: "Retired teacher; walks daily." },
    linkedDaysAgo: 29, adherence: 0.62, start: { flexion: 88, abduction: 66, external_rotation: 14, pendulum: 22 },
    gain: { flexion: 2.6, abduction: 2, external_rotation: 1.4, pendulum: 0.6 }, pain: [5, 4], plan: STD_PLAN,
  },
  {
    patient: { id: "p-sunita", full_name: "Sunita Deshmukh", date_of_birth: "1978-07-21", sex: "female", phone: "+91 99300 76511",
      affected_side: "right", dominant_side: "right", diagnosis: "Adhesive capsulitis, thawing phase", symptom_onset: "2026-02-10",
      conditions: [], medications: null, notes: "Desk job; wants to return to badminton." },
    linkedDaysAgo: 30, adherence: 0.95, start: { flexion: 118, abduction: 92, external_rotation: 30, pendulum: 30 },
    gain: { flexion: 5.5, abduction: 5, external_rotation: 3, pendulum: 0.5 }, pain: [3, 1],
    plan: [item("flexion", 150), item("abduction", 130), item("external_rotation", 55), item("internal_rotation", 50)],
  },
  {
    patient: { id: "p-arjun", full_name: "Arjun Mehta", date_of_birth: "1969-01-30", sex: "male", phone: "+91 98670 33019",
      affected_side: "right", dominant_side: "right", diagnosis: "Adhesive capsulitis, freezing phase", symptom_onset: "2026-07-15",
      conditions: ["Type 2 diabetes", "Hypertension"], medications: "Metformin, Amlodipine", notes: "Pushes through pain." },
    linkedDaysAgo: 24, adherence: 0.85, start: { flexion: 90, abduction: 64, external_rotation: 16, pendulum: 24 },
    gain: { flexion: 4, abduction: 3, external_rotation: 2, pendulum: 0.5 }, pain: [5, 4], painSpikeDays: 6, lean: true,
    plan: STD_PLAN,
  },
  {
    patient: { id: "p-fatima", full_name: "Fatima Shaikh", date_of_birth: "1974-09-08", sex: "female", phone: "+91 99870 50213",
      affected_side: "left", dominant_side: "right", diagnosis: "Adhesive capsulitis, frozen phase", symptom_onset: "2026-05-11",
      conditions: ["Hypothyroidism"], medications: "Levothyroxine 75 mcg OD", notes: "Travels for work." },
    linkedDaysAgo: 27, adherence: 0.8, start: { flexion: 95, abduction: 72, external_rotation: 20, pendulum: 26 },
    gain: { flexion: 4.5, abduction: 3.5, external_rotation: 2.2, pendulum: 0.5 }, pain: [5, 3], skipLastDays: 4,
    plan: STD_PLAN,
  },
  {
    patient: { id: "p-vikram", full_name: "Vikram Nair", date_of_birth: "1963-05-19", sex: "male", phone: "+91 97400 18852",
      affected_side: "left", dominant_side: "left", diagnosis: "Shoulder stiffness, query adhesive capsulitis", symptom_onset: "2026-09-01",
      conditions: ["Type 2 diabetes"], medications: "Glimepiride 1 mg", notes: "Referred by GP; first visit this week." },
    linkedDaysAgo: 2, adherence: 0, start: {}, gain: {}, pain: [6, 6],
  },
];

function sessionsFor(pr: Profile, plan: CarePlan | undefined): Session[] {
  if (!plan) return [];
  const r = rng(pr.patient.id.split("").reduce((a, c) => a * 31 + c.charCodeAt(0), 7));
  const out: Session[] = [];
  const perDay = Math.max(...plan.items.map((i) => i.times_per_day));
  for (let d = pr.linkedDaysAgo - 1; d >= 0; d--) {
    if (pr.skipLastDays && d < pr.skipLastDays) continue;
    const weeks = (pr.linkedDaysAgo - d) / 7;
    for (let k = 0; k < perDay; k++) {
      if (r() > pr.adherence) continue;
      const hour = [8, 13, 19][k] ?? 9;
      if (Date.parse(isoDaysAgo(d, hour)) > Date.now()) continue; // not yet happened today
      const spike = pr.painSpikeDays && d < pr.painSpikeDays ? (pr.painSpikeDays - d) * 0.55 : 0;
      const painAfter = Math.round(
        Math.min(10, Math.max(0, pr.pain[0] + (pr.pain[1] - pr.pain[0]) * (1 - d / pr.linkedDaysAgo) + spike + (r() - 0.5) * 1.4)));
      const exercises: SessionExercise[] = plan.items.map((it) => {
        const total = it.sets * it.reps;
        const rejRate = (pr.lean ? 0.28 + (spike > 0 ? 0.15 : 0) : 0.06) * (0.6 + r() * 0.8);
        const rejected = Math.min(total, Math.round(total * rejRate));
        const base = pr.start[it.exercise_id] ?? 30;
        const gain = (pr.gain[it.exercise_id] ?? 1) * weeks * (1 - 0.06 * weeks);
        const peak = Math.round((base + gain + (r() - 0.5) * 6 - (spike > 1 ? spike * 2.5 : 0)) * 10) / 10;
        const flags: string[] = [];
        if (pr.lean && rejected > 0) flags.push(it.exercise_id === "abduction" ? "TRUNK_LEAN_LATERAL" : "TRUNK_LEAN_SAGITTAL");
        if (it.exercise_id === "external_rotation" && r() < 0.25) flags.push("ELBOW_DRIFT");
        if (!pr.lean && rejected > 1 && r() < 0.3) flags.push("TOO_FAST");
        return { exercise_id: it.exercise_id, reps_counted: total - rejected, reps_rejected: rejected,
          peak_deg: peak, median_deg: Math.round((peak - 6 - r() * 6) * 10) / 10, flags };
      });
      out.push({
        id: `${pr.patient.id}-${d}-${k}`, patient_id: pr.patient.id, plan_id: plan.id,
        started_at: isoDaysAgo(d, hour), duration_s: Math.round(600 + r() * 700),
        source: d % 7 === 3 && k === 0 ? "station" : "home",
        pain_before: Math.max(0, painAfter - Math.round(r() * 2)), pain_after: painAfter, notes: null, exercises,
      });
    }
  }
  return out.reverse();
}

interface Stored {
  clinician: Clinician;
  plans: CarePlan[];
}

function initialStore(): Stored {
  const clinician: Clinician = {
    id: "c-demo", full_name: "Dr. Ananya Rao", title: "Physiotherapist (MPT, Musculoskeletal)", clinic: "Physio Buddy Demo Clinic",
    registration_no: "MH-PT-04417", phone: "+91 98200 00000", referral_code: "PB-7KQ3MX", created_at: isoDaysAgo(60),
  };
  const plans: CarePlan[] = PROFILES.filter((p) => p.plan).map((p) => ({
    id: `plan-${p.patient.id}-1`, patient_id: p.patient.id, version: 1, status: "active" as const,
    notes: "Gentle range work below the pain-stop level; hold at the end of range.", created_at: isoDaysAgo(p.linkedDaysAgo),
    items: p.plan!,
  }));
  return { clinician, plans };
}

function load(): Stored {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) return JSON.parse(raw) as Stored;
  } catch {
    /* private mode or blocked storage: fall back to the seed */
  }
  return initialStore();
}

function save(s: Stored) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(s));
  } catch {
    /* demo still works for this page view */
  }
}

export function resetDemo() {
  try {
    localStorage.removeItem(STORE_KEY);
  } catch {
    /* ignore */
  }
}

export function demoApi(): Api {
  let store = load();
  let signedIn = true;
  const listeners = new Set<() => void>();
  const patients: Patient[] = PROFILES.map((p) => ({
    ...p.patient, created_at: isoDaysAgo(p.linkedDaysAgo + 1), consent_at: isoDaysAgo(p.linkedDaysAgo),
  }));
  // sessions follow each patient's first plan (generated once per page load)
  const sessions: Session[] = PROFILES.flatMap((p) =>
    sessionsFor(p, store.plans.filter((pl) => pl.patient_id === p.patient.id).sort((a, b) => a.version - b.version)[0]));
  const notify = () => listeners.forEach((l) => l());

  return {
    mode: "demo",
    async currentUserEmail() {
      return signedIn ? "ananya.rao@demo.physiobuddy" : null;
    },
    async signIn() {
      signedIn = true;
      notify();
    },
    async signUp() {
      signedIn = true;
      notify();
      return { needsConfirmation: false };
    },
    async signOut() {
      signedIn = false;
      notify();
    },
    onAuthChange(cb) {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    async getMyClinician() {
      return signedIn ? store.clinician : null;
    },
    async saveClinicianProfile(input: ClinicianInput) {
      store = { ...store, clinician: { ...store.clinician, ...input } };
      save(store);
      return store.clinician;
    },
    async regenerateReferralCode() {
      const a = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
      let code = "PB-";
      for (let i = 0; i < 6; i++) code += a[Math.floor(Math.random() * a.length)];
      store = { ...store, clinician: { ...store.clinician, referral_code: code } };
      save(store);
      return code;
    },
    async listExercises() {
      return EXERCISES;
    },
    async listPatients() {
      return patients;
    },
    async getPatient(id) {
      return patients.find((p) => p.id === id) ?? null;
    },
    async listPlans(patientId) {
      return store.plans.filter((p) => !patientId || p.patient_id === patientId).sort((a, b) => b.version - a.version);
    },
    async publishPlan(patientId, notes, items) {
      const prev = store.plans.filter((p) => p.patient_id === patientId);
      const plan: CarePlan = {
        id: `plan-${patientId}-${prev.length + 1}-${Date.now()}`, patient_id: patientId,
        version: Math.max(0, ...prev.map((p) => p.version)) + 1, status: "active", notes: notes || null,
        created_at: new Date().toISOString(), items,
      };
      store = {
        ...store,
        plans: [...store.plans.map((p) => (p.patient_id === patientId ? { ...p, status: "superseded" as const } : p)), plan],
      };
      save(store);
      return plan;
    },
    async listSessions(sinceDays, patientId) {
      const since = Date.now() - sinceDays * DAY;
      return sessions.filter((s) => (!patientId || s.patient_id === patientId) && Date.parse(s.started_at) >= since)
        .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at));
    },
  };
}
