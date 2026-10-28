import QRCode from "qrcode";
import { useEffect, useState, type FormEvent } from "react";
import { AlertCircle, Check, Copy } from "lucide-react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useData } from "../lib/store";
import type { ClinicianInput } from "../lib/types";
import { BrandPanel, ClinicianFields, emptyClinicianInput, SignInButtons } from "./Auth";

const STEPS = ["Account", "Professional details", "Confirm"];

function Stepper({ step }: { step: number }) {
  return (
    <ol className="stepper" aria-label="Sign-up steps">
      {STEPS.map((s, i) => (
        <li key={s} className={i < step ? "done" : i === step ? "current" : ""} aria-current={i === step ? "step" : undefined}>
          <span className="dot">{i < step ? <Check size={13} strokeWidth={3} /> : i + 1}</span>
          <span className="label">{s}</span>
        </li>
      ))}
    </ol>
  );
}

/** New doctor sign-up: 1 account (Google or email), 2 professional details, 3 confirm, then the referral code. */
export function Signup() {
  const { email, user, clinician, reload, setClinician } = useData();
  const nav = useNavigate();
  // signed in (Google / email) but no doctor profile yet: sent here from the sign-in page or the dashboard
  const noAccount = Boolean((useLocation().state as { noAccount?: boolean } | null)?.noAccount);
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<ClinicianInput>(() => emptyClinicianInput(user?.name));
  const [agree, setAgree] = useState({ registered: false, data: false });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [qr, setQr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (user?.name && !form.full_name) setForm((f) => ({ ...f, full_name: user.name ?? "" }));
  }, [user?.name, form.full_name]);
  useEffect(() => {
    if (done && clinician) QRCode.toDataURL(clinician.referral_code, { width: 200, margin: 1, color: { dark: "#0e4f4a", light: "#ffffff" } }).then(setQr).catch(() => setQr(null));
  }, [done, clinician]);

  if (email && clinician && !done) return <Navigate to="/" replace />;
  const current = !email ? 0 : done ? 3 : step;

  const toConfirm = (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setStep(2);
  };
  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      setClinician(await api.saveClinicianProfile(form));
      setDone(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <BrandPanel />
      <div className="auth-form">
        <div className="auth-card" style={{ maxWidth: current === 1 ? 560 : 440 }}>
          {current < 3 ? <Stepper step={current} /> : null}

          {current === 0 ? (
            <>
              <div>
                <h1>Create your doctor account</h1>
                <p className="ink2" style={{ margin: "6px 0 0" }}>For physiotherapists. Takes about two minutes; you get a referral code for your patients at the end.</p>
              </div>
              {api.authMode === "demo" ? <div className="note">Demo mode: the account is simulated, so you can walk through sign-up safely.</div> : null}
              <SignInButtons mode="up" returnTo="/signup" onDone={reload} />
              <p className="muted" style={{ fontSize: 13.5, margin: 0 }}>Already registered? <Link to="/login" style={{ color: "var(--teal)", fontWeight: 600 }}>Sign in</Link></p>
            </>
          ) : null}

          {current === 1 ? (
            <form className="stack" style={{ gap: 16 }} onSubmit={toConfirm}>
              {noAccount ? (
                <div className="alert" role="alert">
                  <AlertCircle size={18} />
                  <span><b>No account found</b>{user?.email ? <> for {user.email}</> : null}. Please sign up: fill in your details below to create your doctor account, or use another account.</span>
                </div>
              ) : null}
              <div>
                <h1>Your professional details</h1>
                <p className="ink2" style={{ margin: "6px 0 0" }}>
                  {user?.email ? <>Signed in as <b>{user.email}</b>. </> : null}Patients see your name, qualification and clinic when they link to you.
                </p>
              </div>
              <ClinicianFields value={form} onChange={setForm} />
              <div className="row between">
                <button type="button" className="btn ghost" onClick={async () => { await api.signOut(); await reload(); }}>Use another account</button>
                <button className="btn">Continue</button>
              </div>
            </form>
          ) : null}

          {current === 2 ? (
            <div className="stack" style={{ gap: 16 }}>
              <div>
                <h1>Check and confirm</h1>
                <p className="ink2" style={{ margin: "6px 0 0" }}>We verify your registration number before your profile shows as verified.</p>
              </div>
              <dl className="kv card card-pad" style={{ margin: 0 }}>
                <dt>Name</dt><dd>{form.full_name}</dd>
                <dt>Qualification</dt><dd>{form.title} · {form.specialization}</dd>
                <dt>Clinic</dt><dd>{form.clinic}, {form.city}</dd>
                <dt>Registration</dt><dd>{form.registration_no} · {form.council}</dd>
                <dt>Experience</dt><dd>{form.years_experience ? `${form.years_experience} years` : "—"}</dd>
                <dt>Phone</dt><dd>{form.phone}</dd>
              </dl>
              <label className="check">
                <input id="agree-registered" type="checkbox" checked={agree.registered} onChange={(e) => setAgree({ ...agree, registered: e.target.checked })} />
                <span>I am a registered physiotherapist and these details are correct.</span>
              </label>
              <label className="check">
                <input id="agree-data" type="checkbox" checked={agree.data} onChange={(e) => setAgree({ ...agree, data: e.target.checked })} />
                <span>I will use patient data only for the care of patients who link to me, and keep it confidential.</span>
              </label>
              {err ? <div className="error">{err}</div> : null}
              <div className="row between">
                <button className="btn ghost" onClick={() => setStep(1)}>Back</button>
                <button className="btn" disabled={busy || !agree.registered || !agree.data} onClick={submit}>{busy ? "Creating…" : "Create my account"}</button>
              </div>
            </div>
          ) : null}

          {current === 3 && clinician ? (
            <div className="stack" style={{ gap: 18 }}>
              <div>
                <h1>Welcome, {clinician.full_name.split(" ").slice(0, 2).join(" ")}</h1>
                <p className="ink2" style={{ margin: "6px 0 0" }}>Your account is ready. Give patients this code; they enter it in the Auri app to link to you.</p>
              </div>
              <div className="row wrap" style={{ gap: 20 }}>
                {qr ? <span className="qr"><img src={qr} width={150} height={150} alt={`QR code for ${clinician.referral_code}`} /></span> : null}
                <div className="stack" style={{ gap: 10 }}>
                  <div className="big-code">{clinician.referral_code}</div>
                  <button className="btn ghost small" onClick={async () => {
                    try { await navigator.clipboard.writeText(clinician.referral_code); setCopied(true); } catch { /* code stays visible */ }
                  }}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "Copied" : "Copy code"}</button>
                </div>
              </div>
              <div className="warn-note">Registration check pending: you can use the dashboard now; your profile shows as verified once the team confirms your registration number.</div>
              <button className="btn" onClick={() => { void reload(); nav("/"); }}>Open my dashboard</button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
