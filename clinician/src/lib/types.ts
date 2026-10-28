// Mirrors clinician/supabase/schema.sql. Degrees always come from the device's geometry; null = unavailable.

export type Sex = "female" | "male" | "other" | "prefer_not_to_say";
export type Side = "left" | "right" | "both";

export interface Clinician {
  id: string;
  full_name: string;
  title: string | null;
  clinic: string | null;
  registration_no: string | null;
  phone: string | null;
  referral_code: string;
  created_at: string;
}

export interface Patient {
  id: string;
  full_name: string;
  date_of_birth: string | null;
  sex: Sex | null;
  phone: string | null;
  affected_side: Side | null;
  dominant_side: "left" | "right" | null;
  diagnosis: string | null;
  symptom_onset: string | null;
  conditions: string[];
  medications: string | null;
  notes: string | null;
  created_at: string;
  consent_at: string; // when the patient linked to this clinician
  video_room: string; // private video-consult room for this patient and clinician
}

export type Metric = "elevation" | "rotation";

export interface Exercise {
  id: string;
  name: string;
  metric: Metric;
  description: string | null;
  default_sets: number;
  default_reps: number;
  default_hold: number;
}

export interface PlanItem {
  exercise_id: string;
  sets: number;
  reps: number;
  hold_s: number;
  times_per_day: number;
  days_per_week: number;
  rom_target_deg: number | null;
  pain_stop: number;
  notes: string | null;
}

export interface CarePlan {
  id: string;
  patient_id: string;
  version: number;
  status: "active" | "superseded";
  notes: string | null;
  created_at: string;
  items: PlanItem[];
}

export interface SessionExercise {
  exercise_id: string;
  reps_counted: number;
  reps_rejected: number;
  peak_deg: number | null;
  median_deg: number | null;
  flags: string[];
}

export interface Session {
  id: string;
  patient_id: string;
  plan_id: string | null;
  started_at: string;
  duration_s: number;
  source: "home" | "station";
  pain_before: number | null;
  pain_after: number | null;
  notes: string | null;
  exercises: SessionExercise[];
}

export interface VideoCall {
  id: string;
  patient_id: string;
  scheduled_for: string | null; // null = started straight away
  duration_min: number;
  status: "scheduled" | "started" | "cancelled";
  started_at: string | null;
  notes: string | null;
  created_at: string;
}

export interface ClinicianInput {
  full_name: string;
  title: string;
  clinic: string;
  registration_no: string;
  phone: string;
}

/** Everything the dashboard reads or writes. Two implementations: Supabase and the demo store. */
export interface Api {
  mode: "supabase" | "demo";
  currentUserEmail(): Promise<string | null>;
  signIn(email: string, password: string): Promise<void>;
  signUp(email: string, password: string): Promise<{ needsConfirmation: boolean }>;
  signOut(): Promise<void>;
  onAuthChange(cb: () => void): () => void;
  getMyClinician(): Promise<Clinician | null>;
  saveClinicianProfile(input: ClinicianInput): Promise<Clinician>;
  regenerateReferralCode(): Promise<string>;
  listExercises(): Promise<Exercise[]>;
  listPatients(): Promise<Patient[]>;
  getPatient(id: string): Promise<Patient | null>;
  listPlans(patientId?: string): Promise<CarePlan[]>; // all versions, newest first
  publishPlan(patientId: string, notes: string, items: PlanItem[]): Promise<CarePlan>;
  listSessions(sinceDays: number, patientId?: string): Promise<Session[]>; // newest first
  listCalls(patientId?: string): Promise<VideoCall[]>;
  scheduleCall(patientId: string, when: string, minutes: number, notes: string): Promise<VideoCall>;
  startCall(patientId: string, scheduledId?: string): Promise<VideoCall>; // logs the call as started
  cancelCall(id: string): Promise<void>;
}
