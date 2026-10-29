// Supabase implementation of the dashboard API (tables and RPCs in clinician/supabase/schema.sql).
// Row-level security does the access control: these queries only ever return the signed-in clinician's patients.
// Sign-in is Auth0 when it is configured (Supabase then trusts Auth0's ID token), otherwise Supabase's own auth.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { auth0, GOOGLE_CONNECTION, handleAuth0Redirect, idToken } from "./auth0";
import { yearsForStorage } from "./practice";
import type { Api, AuthUser, CarePlan, Clinician, Patient, PlanItem, Session, VideoCall } from "./types";

const DAY = 86_400_000;

function must<T>(res: { data: T | null; error: { message: string } | null }): T {
  if (res.error) throw new Error(res.error.message);
  return res.data as T;
}

type PlanRow = Omit<CarePlan, "items"> & { plan_items: (PlanItem & { position: number })[] };

const toPlan = (r: PlanRow): CarePlan => ({
  id: r.id, patient_id: r.patient_id, version: r.version, status: r.status, notes: r.notes, created_at: r.created_at,
  items: [...(r.plan_items ?? [])].sort((a, b) => a.position - b.position).map((i) => ({
    exercise_id: i.exercise_id, sets: i.sets, reps: i.reps, hold_s: i.hold_s, times_per_day: i.times_per_day,
    days_per_week: i.days_per_week, rom_target_deg: i.rom_target_deg === null ? null : Number(i.rom_target_deg),
    pain_stop: i.pain_stop, notes: i.notes,
  })),
});

export function supabaseApi(url: string, anonKey: string, useAuth0: boolean): Api {
  // With Auth0, supabase-js sends Auth0's ID token on every request (and its own sb.auth.* methods are off).
  const sb: SupabaseClient = useAuth0 ? createClient(url, anonKey, { accessToken: idToken }) : createClient(url, anonKey);
  const listeners = new Set<() => void>();
  let clinicianId: string | null = null;

  const sub = async (): Promise<string> => {
    if (useAuth0) {
      const u = await (await auth0()).getUser();
      if (!u?.sub) throw new Error("Not signed in");
      return u.sub;
    }
    const { data } = await sb.auth.getUser();
    if (!data.user) throw new Error("Not signed in");
    return data.user.id;
  };
  const myClinicianId = async (): Promise<string> => {
    if (clinicianId) return clinicianId;
    const row = must(await sb.from("clinicians").select("id").eq("auth_sub", await sub()).maybeSingle()) as { id: string } | null;
    if (!row) throw new Error("Finish your doctor profile first");
    clinicianId = row.id;
    return clinicianId;
  };
  const back = (returnTo: string) => window.location.origin + returnTo;
  const notify = () => listeners.forEach((l) => l());

  const api: Api = {
    mode: "supabase",
    authMode: useAuth0 ? "auth0" : "supabase",
    async currentUser(): Promise<AuthUser | null> {
      if (useAuth0) {
        const a = await auth0();
        if (!(await a.isAuthenticated())) return null;
        const u = await a.getUser();
        return { email: u?.email ?? null, name: u?.name ?? null, picture: u?.picture ?? null };
      }
      const { data } = await sb.auth.getSession();
      const u = data.session?.user;
      if (!u) return null;
      const meta = u.user_metadata ?? {};
      return { email: u.email ?? null, name: (meta.full_name as string) ?? null, picture: (meta.avatar_url as string) ?? null };
    },
    async completeRedirect() {
      return useAuth0 ? handleAuth0Redirect() : null; // supabase-js finishes its own OAuth redirect on load
    },
    async signInWithGoogle(returnTo) {
      if (useAuth0) {
        await (await auth0()).loginWithRedirect({ authorizationParams: { connection: GOOGLE_CONNECTION }, appState: { returnTo } });
        return;
      }
      const { error } = await sb.auth.signInWithOAuth({ provider: "google", options: { redirectTo: back(returnTo) } });
      if (error) throw new Error(error.message);
    },
    async signInWithEmail(returnTo, email, password) {
      if (useAuth0) {
        await (await auth0()).loginWithRedirect({ appState: { returnTo } });
        return;
      }
      const { error } = await sb.auth.signInWithPassword({ email: email ?? "", password: password ?? "" });
      if (error) throw new Error(error.message);
      notify();
    },
    async signUp(method, returnTo, email, password) {
      if (method === "google") {
        await api.signInWithGoogle(returnTo);
        return { needsConfirmation: false };
      }
      if (useAuth0) {
        await (await auth0()).loginWithRedirect({ authorizationParams: { screen_hint: "signup" }, appState: { returnTo } });
        return { needsConfirmation: false };
      }
      const { data, error } = await sb.auth.signUp({
        email: email ?? "", password: password ?? "", options: { emailRedirectTo: back(returnTo) },
      });
      if (error) throw new Error(error.message);
      notify();
      return { needsConfirmation: !data.session };
    },
    async signOut() {
      clinicianId = null;
      if (useAuth0) {
        await (await auth0()).logout({ logoutParams: { returnTo: window.location.origin } });
        return;
      }
      await sb.auth.signOut();
    },
    onAuthChange(cb) {
      listeners.add(cb);
      if (useAuth0) return () => { listeners.delete(cb); };
      const { data } = sb.auth.onAuthStateChange(() => cb());
      return () => {
        listeners.delete(cb);
        data.subscription.unsubscribe();
      };
    },
    async getMyClinician() {
      const row = must(await sb.from("clinicians").select("*").eq("auth_sub", await sub()).maybeSingle()) as Clinician | null;
      clinicianId = row?.id ?? null;
      return row;
    },
    async saveClinicianProfile(input) {
      const row = must(await sb.rpc("create_clinician_profile", {
        p: { ...input, years_experience: yearsForStorage(input.years_experience) },
      })) as Clinician;
      clinicianId = row.id;
      return row;
    },
    async regenerateReferralCode() {
      return must(await sb.rpc("regenerate_referral_code")) as string;
    },
    async listExercises() {
      return must(await sb.from("exercises").select("*").order("id"));
    },
    async listPatients() {
      const id = await myClinicianId();
      const rows = must(await sb.from("care_links").select("consent_at, video_room, patients(*)").eq("clinician_id", id)
        .eq("status", "active")) as unknown as { consent_at: string; video_room: string; patients: Omit<Patient, "consent_at" | "video_room"> | null }[];
      return rows.filter((r) => r.patients).map((r) => ({
        ...r.patients!, conditions: r.patients!.conditions ?? [], consent_at: r.consent_at, video_room: r.video_room,
      }));
    },
    async getPatient(id) {
      return (await api.listPatients()).find((p) => p.id === id) ?? null;
    },
    async listPlans(patientId) {
      let q = sb.from("care_plans").select("*, plan_items(*)").order("version", { ascending: false });
      if (patientId) q = q.eq("patient_id", patientId);
      return (must(await q) as PlanRow[]).map(toPlan);
    },
    async publishPlan(patientId, notes, items) {
      const planId = must(await sb.rpc("publish_care_plan", { p_patient: patientId, p_notes: notes, p_items: items })) as string;
      const row = must(await sb.from("care_plans").select("*, plan_items(*)").eq("id", planId).single()) as PlanRow;
      return toPlan(row);
    },
    async listSessions(sinceDays, patientId) {
      let q = sb.from("sessions").select("*, session_exercises(*)")
        .gte("started_at", new Date(Date.now() - sinceDays * DAY).toISOString())
        .order("started_at", { ascending: false });
      if (patientId) q = q.eq("patient_id", patientId);
      const rows = must(await q) as (Omit<Session, "exercises"> & { session_exercises: Session["exercises"] })[];
      return rows.map(({ session_exercises, ...s }) => ({
        ...s,
        exercises: (session_exercises ?? []).map((e) => ({
          ...e, peak_deg: e.peak_deg === null ? null : Number(e.peak_deg),
          median_deg: e.median_deg === null ? null : Number(e.median_deg), flags: e.flags ?? [],
        })),
      }));
    },
    async listCalls(patientId) {
      let q = sb.from("video_calls").select("*").order("created_at", { ascending: false });
      if (patientId) q = q.eq("patient_id", patientId);
      return must(await q) as VideoCall[];
    },
    async scheduleCall(patientId, when, minutes, notes) {
      return must(await sb.from("video_calls").insert({
        patient_id: patientId, clinician_id: await myClinicianId(), scheduled_for: when, duration_min: minutes, notes: notes || null,
      }).select().single()) as VideoCall;
    },
    async startCall(patientId, scheduledId) {
      const now = new Date().toISOString();
      if (scheduledId) {
        return must(await sb.from("video_calls").update({ status: "started", started_at: now }).eq("id", scheduledId)
          .select().single()) as VideoCall;
      }
      return must(await sb.from("video_calls").insert({
        patient_id: patientId, clinician_id: await myClinicianId(), status: "started", started_at: now,
      }).select().single()) as VideoCall;
    },
    async cancelCall(id) {
      must(await sb.from("video_calls").update({ status: "cancelled" }).eq("id", id));
    },
  };
  return api;
}
