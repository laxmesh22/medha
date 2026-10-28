import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import { summarize, SEVERITY_ORDER, type PatientSummary } from "./stats";
import type { CarePlan, Clinician, Exercise, Patient, Session } from "./types";

export const HISTORY_DAYS = 42;

interface Data {
  loading: boolean;
  error: string | null;
  email: string | null;
  clinician: Clinician | null;
  exercises: Exercise[];
  patients: Patient[];
  plans: CarePlan[];
  sessions: Session[];
  summaries: PatientSummary[]; // most urgent first
  exerciseName: (id: string) => string;
  reload: () => Promise<void>;
  setClinician: (c: Clinician) => void;
}

const Ctx = createContext<Data | null>(null);

export function DataProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Omit<Data, "summaries" | "exerciseName" | "reload" | "setClinician">>({
    loading: true, error: null, email: null, clinician: null, exercises: [], patients: [], plans: [], sessions: [],
  });

  const reload = useCallback(async () => {
    try {
      const email = await api.currentUserEmail();
      if (!email) {
        setState((s) => ({ ...s, loading: false, error: null, email: null, clinician: null }));
        return;
      }
      const clinician = await api.getMyClinician();
      if (!clinician) {
        setState((s) => ({ ...s, loading: false, error: null, email, clinician: null }));
        return;
      }
      const [exercises, patients, plans, sessions] = await Promise.all([
        api.listExercises(), api.listPatients(), api.listPlans(), api.listSessions(HISTORY_DAYS),
      ]);
      sessions.sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at));
      setState({ loading: false, error: null, email, clinician, exercises, patients, plans, sessions });
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
    };
  }, [state, reload]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useData(): Data {
  const v = useContext(Ctx);
  if (!v) throw new Error("useData outside DataProvider");
  return v;
}
