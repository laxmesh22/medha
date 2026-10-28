import { ActivitySquare, ClipboardList, KeyRound, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useData } from "../lib/store";

function BrandPanel() {
  return (
    <div className="auth-brand">
      <div className="row" style={{ gap: 12 }}>
        <span className="brand-mark" aria-hidden>
          <svg width="20" height="20" viewBox="0 0 32 32"><path d="M7 23 L15 9 L25 23" stroke="currentColor" strokeWidth="3.4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </span>
        <span className="brand-name">Physio Buddy</span>
      </div>
      <div>
        <h1>Your patients' shoulder rehab, measured between visits.</h1>
        <div className="auth-points">
          <div><KeyRound size={20} /><span>Patients link to you with your referral code and consent to share their data.</span></div>
          <div><ClipboardList size={20} /><span>You prescribe the exercises, reps and range targets. Nothing changes without you.</span></div>
          <div><ActivitySquare size={20} /><span>See range of motion from the sensors, adherence, pain and form flags every day.</span></div>
          <div><ShieldCheck size={20} /><span>Each physiotherapist sees only their own linked patients.</span></div>
        </div>
      </div>
      <p style={{ fontSize: 13 }}>Clinic station: Jetson Orin Nano + RealSense D455f · Wearable straps: BNO085</p>
    </div>
  );
}

export function Login() {
  const { email: signedIn, clinician, reload } = useData();
  const nav = useNavigate();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (signedIn && clinician) return <Navigate to="/" replace />;
  if (signedIn && !clinician) return <Navigate to="/onboarding" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      if (mode === "in") await api.signIn(email, password);
      else {
        const r = await api.signUp(email, password);
        if (r.needsConfirmation) {
          setMsg("Check your email to confirm the account, then sign in.");
          setMode("in");
          return;
        }
      }
      await reload();
      nav("/");
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <BrandPanel />
      <div className="auth-form">
        <form className="auth-card" onSubmit={submit}>
          <div>
            <h1>{mode === "in" ? "Sign in" : "Create your clinician account"}</h1>
            <p className="ink2" style={{ margin: "6px 0 0" }}>For physiotherapists and clinicians.</p>
          </div>
          {api.mode === "demo" ? (
            <div className="note">
              Demo mode: no Supabase project is configured, so the dashboard runs on fictional patients.
              <div style={{ marginTop: 10 }}>
                <button type="button" className="btn" onClick={async () => { await api.signIn("", ""); await reload(); nav("/"); }}>
                  Open the demo
                </button>
              </div>
            </div>
          ) : null}
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="pw">Password</label>
            <input id="pw" className="input" type="password" autoComplete={mode === "in" ? "current-password" : "new-password"}
              minLength={8} required value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {err ? <div className="error">{err}</div> : null}
          {msg ? <div className="note">{msg}</div> : null}
          <button className="btn" disabled={busy}>{busy ? "Please wait…" : mode === "in" ? "Sign in" : "Create account"}</button>
          <button type="button" className="btn ghost" onClick={() => setMode(mode === "in" ? "up" : "in")}>
            {mode === "in" ? "New here? Create an account" : "Have an account? Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}

export function ClinicianForm({ onDone, submitLabel }: { onDone?: () => void; submitLabel: string }) {
  const { clinician, setClinician } = useData();
  const [f, setF] = useState({
    full_name: clinician?.full_name ?? "", title: clinician?.title ?? "Physiotherapist", clinic: clinician?.clinic ?? "",
    registration_no: clinician?.registration_no ?? "", phone: clinician?.phone ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      setClinician(await api.saveClinicianProfile(f));
      onDone?.();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="stack" onSubmit={submit} style={{ gap: 14 }}>
      <div className="field"><label htmlFor="fn">Full name</label><input id="fn" className="input" required value={f.full_name} onChange={set("full_name")} placeholder="Dr. Firstname Lastname" /></div>
      <div className="field"><label htmlFor="ti">Title / qualification</label><input id="ti" className="input" value={f.title} onChange={set("title")} /></div>
      <div className="field"><label htmlFor="cl">Clinic or hospital</label><input id="cl" className="input" value={f.clinic} onChange={set("clinic")} /></div>
      <div className="grid grid-2" style={{ gap: 14 }}>
        <div className="field"><label htmlFor="rg">Registration no.</label><input id="rg" className="input" value={f.registration_no} onChange={set("registration_no")} /></div>
        <div className="field"><label htmlFor="ph">Phone</label><input id="ph" className="input" value={f.phone} onChange={set("phone")} /></div>
      </div>
      {err ? <div className="error">{err}</div> : null}
      <div><button className="btn" disabled={busy}>{busy ? "Saving…" : submitLabel}</button></div>
    </form>
  );
}

export function Onboarding() {
  const { email, clinician } = useData();
  const nav = useNavigate();
  if (!email) return <Navigate to="/login" replace />;
  if (clinician) return <Navigate to="/" replace />;
  return (
    <div className="auth">
      <BrandPanel />
      <div className="auth-form">
        <div className="auth-card">
          <div>
            <h1>Set up your profile</h1>
            <p className="ink2" style={{ margin: "6px 0 0" }}>Patients see your name and clinic when they enter your referral code.
              The code is created when you save.</p>
          </div>
          <ClinicianForm submitLabel="Save and get my referral code" onDone={() => nav("/profile")} />
        </div>
      </div>
    </div>
  );
}
