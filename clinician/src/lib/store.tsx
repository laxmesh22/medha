import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import { summarize, SEVERITY_ORDER, type PatientSummary } from "./stats";
import type { AuthUser, CarePlan, Clinician, Exercise, Patient, Session, VideoCall } from "./types";

export const HISTORY_DAYS = 42;

interface Data {
  loading: boolean;
  error: string | null;
  email: string | null;
  user: AuthUser | null;
  /** where to go after an Auth0 / OAuth redirect finished (consumed by the router) */
  redirectTo: string | null;
  clinician: Clinician | null;
  exercises: Exercise[];
  patients: Patient[];
  plans: CarePlan[];
  sessions: Session[];
  calls: VideoCall[];
  summaries: PatientSummary[]; // most urgent first
  exerciseName: (id: string) => string;
  reload: () => Promise<void>;
  setClinician: (c: Clinician) => void;
  clearRedirect: () => void;
}

const Ctx = createContext<Data | null>(null);

export function DataProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Omit<Data, "summaries" | "exerciseName" | "reload" | "setClinician" | "clearRedirect">>({
    loading: true, error: null, email: null, user: null, redirectTo: null, clinician: null, exercises: [], patients: [],
    plans: [], sessions: [], calls: [],
  });

  const reload = useCallback(async () => {
    try {
      const redirectTo = await api.completeRedirect();
      const user = await api.currentUser();
      const email = user ? user.email ?? "signed-in" : null;
      if (!user) {
        setState((s) => ({ ...s, loading: false, error: null, email: null, user: null, clinician: null, redirectTo }));
        return;
      }
      // Create-account returns from Google straight into the form. Do not look up a clinician row first.
      if (redirectTo === "/signup") {
        setState((s) => ({ ...s, loading: false, error: null, email, user, clinician: null, redirectTo }));
        return;
      }
      const clinician = await api.getMyClinician();
      if (!clinician) {
        setState((s) => ({ ...s, loading: false, error: null, email, user, clinician: null, redirectTo: redirectTo ?? s.redirectTo }));
        return;
      }
      const [exercises, patients, plans, sessions, calls] = await Promise.all([
        api.listExercises(), api.listPatients(), api.listPlans(), api.listSessions(HISTORY_DAYS), api.listCalls(),
      ]);
      sessions.sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at));
      setState((s) => ({ loading: false, error: null, email, user, redirectTo: redirectTo ?? s.redirectTo, clinician, exercises,
        patients, plans, sessions, calls }));
    } catch (e) {
      setState((s) => ({ ...s, loading: false, error: e instanceof Error ? e.message : String(e) }));
    }
  }, []);

  useEffect(() => {
    void reload();
    return api.onAuthChange(() => void reload());
  }, [reload]);

  const value = useMemo<Data>(() => {
    const summaries = state.patients
      .map((p) => summarize(p, state.plans, state.sessions))
      .sort((a, b) => SEVERITY_ORDER[b.status] - SEVERITY_ORDER[a.status] || a.patient.full_name.localeCompare(b.patient.full_name));
    const names = new Map(state.exercises.map((e) => [e.id, e.name]));
    return {
      ...state, summaries, reload,
      exerciseName: (id) => names.get(id) ?? id,
      setClinician: (c) => setState((s) => ({ ...s, clinician: c })),
      clearRedirect: () => setState((s) => ({ ...s, redirectTo: null })),
    };
  }, [state, reload]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useData(): Data {
  const v = useContext(Ctx);
  if (!v) throw new Error("useData outside DataProvider");
  return v;
}
