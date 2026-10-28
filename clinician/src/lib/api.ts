import { auth0Configured } from "./auth0";
import { demoApi } from "./demo";
import { supabaseApi } from "./supabaseApi";
import type { Api } from "./types";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const key = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

const forceDemo = import.meta.env.VITE_FORCE_DEMO === "1"; // the shared preview build (no backend access)

/** Supabase when the project keys are set (clinician/.env), otherwise the built-in demo store. */
export const api: Api = url && key && !forceDemo ? supabaseApi(url, key, auth0Configured) : demoApi();
