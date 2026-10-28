import { demoApi } from "./demo";
import { supabaseApi } from "./supabaseApi";
import type { Api } from "./types";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const key = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

/** Supabase when the project keys are set (clinician/.env), otherwise the built-in demo store. */
export const api: Api = url && key ? supabaseApi(url, key) : demoApi();
