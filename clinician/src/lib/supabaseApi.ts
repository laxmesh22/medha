// Supabase implementation of the dashboard API (tables and RPCs in clinician/supabase/schema.sql).
// Row-level security does the access control: these queries only ever return the signed-in clinician's patients.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Api, CarePlan, Clinician, Patient, PlanItem, Session, VideoCall } from "./types";

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

export function supabaseApi(url: string, anonKey: string): Api {
  const sb: SupabaseClient = createClient(url, anonKey);

  const uid = async () => {
    const { data } = await sb.auth.getUser();
    if (!data.user) throw new Error("Not signed in");
    return data.user.id;
  };

  return {
    mode: "supabase",
    async currentUserEmail() {
      const { data } = await sb.auth.getSession();
      return data.session?.user.email ?? null;
    },
    async signIn(email, password) {
      const { error } = await sb.auth.signInWithPassword({ email, password });
      if (error) throw new Error(error.message);
    },
    async signUp(email, password) {
      const { data, error } = await sb.auth.signUp({ email, password });
      if (error) throw new Error(error.message);
      return { needsConfirmation: !data.session };
    },
    async signOut() {
      await sb.auth.signOut();
    },
    onAuthChange(cb) {
      const { data } = sb.auth.onAuthStateChange(() => cb());
      return () => data.subscription.unsubscribe();
    },
    async getMyClinician() {
      const id = await uid();
      return must(await sb.from("clinicians").select("*").eq("id", id).maybeSingle()) as Clinician | null;
    },
    async saveClinicianProfile(input) {
      return must(await sb.rpc("create_clinician_profile", {
        p_full_name: input.full_name, p_clinic: input.clinic, p_registration_no: input.registration_no,
        p_phone: input.phone, p_title: input.title,
      })) as Clinician;
    },
    async regenerateReferralCode() {
      return must(await sb.rpc("regenerate_referral_code")) as string;
    },
    async listExercises() {
      return must(await sb.from("exercises").select("*").order("id"));
    },
    async listPatients() {
      const id = await uid();
      const rows = must(await sb.from("care_links").select("consent_at, video_room, patients(*)").eq("clinician_id", id)
        .eq("status", "active")) as unknown as { consent_at: string; video_room: string; patients: Omit<Patient, "consent_at" | "video_room"> | null }[];
      return rows.filter((r) => r.patients).map((r) => ({
        ...r.patients!, conditions: r.patients!.conditions ?? [], consent_at: r.consent_at, video_room: r.video_room,
      }));
    },
    async getPatient(id) {
      return (await this.listPatients()).find((p) => p.id === id) ?? null;
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
        patient_id: patientId, clinician_id: await uid(), scheduled_for: when, duration_min: minutes, notes: notes || null,
      }).select().single()) as VideoCall;
    },
    async startCall(patientId, scheduledId) {
      const now = new Date().toISOString();
      if (scheduledId) {
        return must(await sb.from("video_calls").update({ status: "started", started_at: now }).eq("id", scheduledId)
          .select().single()) as VideoCall;
      }
      return must(await sb.from("video_calls").insert({
        patient_id: patientId, clinician_id: await uid(), status: "started", started_at: now,
      }).select().single()) as VideoCall;
    },
    async cancelCall(id) {
      must(await sb.from("video_calls").update({ status: "cancelled" }).eq("id", id));
    },
  };
}
