// Mirrors clinician/supabase/schema.sql. Degrees always come from the device's geometry; null = unavailable.

export type Sex = "female" | "male" | "other" | "prefer_not_to_say";
export type Side = "left" | "right" | "both";

export interface Clinician {
  id: string;
  email: string | null;
  full_name: string;
  title: string | null;
  specialization: string | null;
  clinic: string | null;
  city: string | null;
  council: string | null;
  registration_no: string | null;
  years_experience: number | null;
  phone: string | null;
  referral_code: string;
  verification_status: "pending" | "verified" | "rejected";
  created_at: string;
}

export interface AuthUser {
  email: string | null;
  name: string | null;
  picture: string | null;
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
  /** Intake answers with no column of their own, plus language and text_size. */
  intake?: Record<string, unknown>;
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
  /** Null when the phone could not classify the rep. */
  reps_rejected: number | null;
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
  ended_early?: boolean | null;
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

/** One submitted intake. Older versions stay. */
export interface PatientIntake {
  id: string;
  patient_id: string;
  version: number;
  submitted_at: string;
  date_of_birth: string | null;
  sex: string | null;
  gender: string | null;
  affected_side: string | null;
  onset: string | null;
  trigger: string | null;
  trigger_note: string | null;
  main_problem: string | null;
  pain_now: number | null;
  sleep: string | null;
  hard_tasks: string[];
  load: string | null;
  load_increased: string | null;
  load_note: string | null;
  past_injury: string | null;
  past_injury_when: string | null;
  prior_frozen: string | null;
  conditions: string[];
  seen_before: string | null;
  seen_who: string[];
  extra: Record<string, unknown>;
}

export interface PatientConsent {
  id: string;
  patient_id: string;
  kind: "privacy" | "share_with_clinician";
  version: string;
  agreed_at: string;
  clinician_id: string | null;
}

export interface ClinicianInput {
  full_name: string;
  title: string;
  specialization: string;
  clinic: string;
  city: string;
  council: string;
  registration_no: string;
  years_experience: string; // kept as typed; the database stores an integer
  phone: string;
}

/** Everything the dashboard reads or writes. Two implementations: Supabase and the demo store. */
export interface Api {
  mode: "supabase" | "demo";
  /** who signs people in: Auth0 (Google or email, hosted login page), Supabase's own auth, or the demo */
  authMode: "auth0" | "supabase" | "demo";
  currentUser(): Promise<AuthUser | null>;
  /** finish an Auth0 / OAuth redirect if the URL carries one; returns the path to continue at */
  completeRedirect(): Promise<string | null>;
  signInWithGoogle(returnTo: string): Promise<void>;
  /** auth0: opens the hosted login page (no credentials here); supabase: email + password */
  signInWithEmail(returnTo: string, email?: string, password?: string): Promise<void>;
  /** new doctor account; auth0 opens the hosted sign-up page */
  signUp(method: "google" | "email", returnTo: string, email?: string, password?: string): Promise<{ needsConfirmation: boolean }>;
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
  listIntakes(patientId?: string): Promise<PatientIntake[]>;
  listConsents(patientId?: string): Promise<PatientConsent[]>;
  scheduleCall(patientId: string, when: string, minutes: number, notes: string): Promise<VideoCall>;
  startCall(patientId: string, scheduledId?: string): Promise<VideoCall>; // logs the call as started
  cancelCall(id: string): Promise<void>;
}
