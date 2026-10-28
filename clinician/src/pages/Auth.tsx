import { ActivitySquare, ClipboardList, KeyRound, Mail, ShieldCheck, Video } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { AuriLockup } from "../components/Logo";
import { api } from "../lib/api";
import { useData } from "../lib/store";
import type { ClinicianInput } from "../lib/types";

export function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

export function BrandPanel() {
  return (
    <div className="auth-brand">
      <AuriLockup size={52} tone="teal" sub="Assisted upper-limb rehabilitation intelligence" />
      <div>
        <h1>Your patients' shoulder rehab, measured between visits.</h1>
        <div className="auth-points">
          <div><KeyRound size={20} /><span>Patients link to you with your referral code and consent to share their data.</span></div>
          <div><ClipboardList size={20} /><span>You prescribe the exercises, reps and range targets. Nothing changes without you.</span></div>
          <div><ActivitySquare size={20} /><span>See range of motion from the sensors, adherence, pain and form flags every day.</span></div>
          <div><Video size={20} /><span>Book and hold video consults with each patient.</span></div>
          <div><ShieldCheck size={20} /><span>Each physiotherapist sees only their own linked patients.</span></div>
        </div>
      </div>
    </div>
  );
}

/** Google + email buttons. With Auth0 both go to Auth0's hosted page; with Supabase auth email shows a form. */
export function SignInButtons({ mode, returnTo, onDone }: { mode: "in" | "up"; returnTo: string; onDone?: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<"google" | "email" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const passwordForm = api.authMode === "supabase";

  const run = async (which: "google" | "email", fn: () => Promise<unknown>) => {
    setBusy(which);
    setErr(null);
    setMsg(null);
    try {
      const r = await fn();
      if (r && typeof r === "object" && "needsConfirmation" in r && r.needsConfirmation) {
        setMsg("Check your email to confirm the account, then sign in.");
        return;
      }
      onDone?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const google = () => run("google", () => mode === "in" ? api.signInWithGoogle(returnTo) : api.signUp("google", returnTo));
  const emailGo = (e?: FormEvent) => {
    e?.preventDefault();
    return run("email", () => mode === "in" ? api.signInWithEmail(returnTo, email, password) : api.signUp("email", returnTo, email, password));
  };

  return (
    <div className="stack" style={{ gap: 12 }}>
      <button type="button" className="btn google" disabled={busy !== null} onClick={google}>
        <GoogleMark />{busy === "google" ? "Opening Google…" : "Continue with Google"}
      </button>
      {passwordForm ? (
        <form className="stack" style={{ gap: 12 }} onSubmit={emailGo}>
          <div className="divider"><span>or with email</span></div>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="pw">Password</label>
            <input id="pw" className="input" type="password" autoComplete={mode === "in" ? "current-password" : "new-password"}
              minLength={8} required value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <button className="btn" disabled={busy !== null}>{busy === "email" ? "Please wait…" : mode === "in" ? "Sign in" : "Create account"}</button>
        </form>
      ) : (
        <button type="button" className="btn ghost" disabled={busy !== null} onClick={() => emailGo()}>
          <Mail size={17} />{busy === "email" ? "Opening…" : mode === "in" ? "Continue with email" : "Sign up with email"}
        </button>
      )}
      {err ? <div className="error">{err}</div> : null}
      {msg ? <div className="note">{msg}</div> : null}
      <p className="muted" style={{ fontSize: 14.5, margin: 0 }}>
        {api.authMode === "auth0" ? "Secure sign-in by Auth0. " : null}
        {api.authMode === "demo" ? "Demo: no real account is created and nothing leaves this page. " : null}
        We only use your name and email to set up your clinician account.
      </p>
    </div>
  );
}

export function Login() {
  const { email: signedIn, clinician, reload } = useData();
  const nav = useNavigate();
  if (signedIn && clinician) return <Navigate to="/" replace />;
  if (signedIn && !clinician) return <Navigate to="/signup" replace state={{ noAccount: true }} />;
  return (
    <div className="auth">
      <BrandPanel />
      <div className="auth-form">
        <div className="auth-card">
          <div>
            <h1>Sign in</h1>
            <p className="ink2" style={{ margin: "6px 0 0" }}>Auri for physiotherapists and clinicians.</p>
          </div>
          {api.authMode === "demo" ? (
            <div className="note">Demo mode: sign-in is simulated and the dashboard shows fictional patients.</div>
          ) : null}
          <SignInButtons mode="in" returnTo="/" onDone={async () => { await reload(); nav("/"); }} />
          <div className="divider"><span>New to Auri?</span></div>
          <Link to="/signup" className="btn ghost">Create a doctor account</Link>
        </div>
      </div>
    </div>
  );
}

export const SPECIALIZATIONS = ["Musculoskeletal", "Orthopaedic", "Sports", "Neurological", "Geriatric", "Cardiopulmonary", "Paediatric", "Other"];

export function emptyClinicianInput(name?: string | null): ClinicianInput {
  return { full_name: name ?? "", title: "", specialization: "Musculoskeletal", clinic: "", city: "", council: "",
    registration_no: "", years_experience: "", phone: "" };
}

/** Professional details, shared by doctor sign-up and the profile page. */
export function ClinicianFields({ value, onChange }: { value: ClinicianInput; onChange: (v: ClinicianInput) => void }) {
  const set = (k: keyof ClinicianInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => onChange({ ...value, [k]: e.target.value });
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="field"><label htmlFor="fn">Full name</label>
        <input id="fn" className="input" required value={value.full_name} onChange={set("full_name")} placeholder="Dr. Firstname Lastname" autoComplete="name" /></div>
      <div className="grid grid-2" style={{ gap: 14 }}>
        <div className="field"><label htmlFor="ti">Qualification</label>
          <input id="ti" className="input" required value={value.title} onChange={set("title")} placeholder="e.g. BPT, MPT (Musculoskeletal)" /></div>
        <div className="field"><label htmlFor="sp">Specialisation</label>
          <select id="sp" className="input" value={value.specialization} onChange={set("specialization")}>
            {SPECIALIZATIONS.map((s) => <option key={s}>{s}</option>)}
          </select></div>
      </div>
      <div className="grid grid-2" style={{ gap: 14 }}>
        <div className="field"><label htmlFor="cl">Clinic or hospital</label>
          <input id="cl" className="input" required value={value.clinic} onChange={set("clinic")} /></div>
        <div className="field"><label htmlFor="ci">City</label>
          <input id="ci" className="input" required value={value.city} onChange={set("city")} autoComplete="address-level2" /></div>
      </div>
      <div className="grid grid-2" style={{ gap: 14 }}>
        <div className="field"><label htmlFor="co">Registering council</label>
          <input id="co" className="input" required value={value.council} onChange={set("council")} placeholder="Your state physiotherapy council" /></div>
        <div className="field"><label htmlFor="rg">Registration number</label>
          <input id="rg" className="input" required value={value.registration_no} onChange={set("registration_no")} /></div>
      </div>
      <div className="grid grid-2" style={{ gap: 14 }}>
        <div className="field"><label htmlFor="yx">Years of experience</label>
          <input id="yx" className="input num" type="number" min={0} max={70} value={value.years_experience} onChange={set("years_experience")} /></div>
        <div className="field"><label htmlFor="ph">Phone</label>
          <input id="ph" className="input" type="tel" required value={value.phone} onChange={set("phone")} autoComplete="tel" placeholder="+91" /></div>
      </div>
    </div>
  );
}

/** Profile page form: edit the signed-in doctor's details. */
export function ClinicianForm({ submitLabel }: { submitLabel: string }) {
  const { clinician, setClinician } = useData();
  const [f, setF] = useState<ClinicianInput>(() => clinician ? {
    full_name: clinician.full_name, title: clinician.title ?? "", specialization: clinician.specialization ?? "Musculoskeletal",
    clinic: clinician.clinic ?? "", city: clinician.city ?? "", council: clinician.council ?? "",
    registration_no: clinician.registration_no ?? "", years_experience: clinician.years_experience?.toString() ?? "",
    phone: clinician.phone ?? "",
  } : emptyClinicianInput());
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setSaved(false);
    try {
      setClinician(await api.saveClinicianProfile(f));
      setSaved(true);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="stack" onSubmit={submit} style={{ gap: 14 }}>
      <ClinicianFields value={f} onChange={setF} />
      {err ? <div className="error">{err}</div> : null}
      <div className="row"><button className="btn" disabled={busy}>{busy ? "Saving…" : submitLabel}</button>{saved ? <span className="muted">Saved</span> : null}</div>
    </form>
  );
}
