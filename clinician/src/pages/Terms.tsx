import { Link } from "react-router-dom";
import { BrandPanel } from "./Auth";

/** Terms shown during doctor sign-up, and at /terms. Not a substitute for a lawyer-drafted contract. */
export function Terms({ onBack }: { onBack?: () => void }) {
  return (
    <div className="auth">
      <BrandPanel />
      <div className="auth-form">
        <div className="auth-card" style={{ maxWidth: 640 }}>
          <div>
            <h1>Terms and conditions</h1>
            <p className="ink2" style={{ margin: "6px 0 0" }}>For physiotherapists creating an Auri clinician account. Please read this before you register.</p>
          </div>
          <div className="stack" style={{ gap: 14, fontSize: 14.5, lineHeight: 1.5 }}>
            <section>
              <h2>Your account</h2>
              <p className="ink2">Auri is for registered physiotherapists. You sign up with Google. We take the name and email from that Google account and continue on this form. We do not search for an existing doctor record before you register.</p>
            </section>
            <section>
              <h2>Licence details</h2>
              <p className="ink2">The council, licence number and the year you started practising must be yours and true. Your profile stays unverified until the team checks them. Choosing a council does not contact that council, and it does not by itself prove your licence.</p>
            </section>
            <section>
              <h2>Patients</h2>
              <p className="ink2">Patients link to you with your referral code and agree to share their data. You use that data only for their care, and you keep it confidential. You see only patients linked to you.</p>
            </section>
            <section>
              <h2>Care plans and measurements</h2>
              <p className="ink2">You set the exercises, reps and range targets. Auri does not diagnose, does not change a plan on its own, and does not replace your clinical judgement. Angles come from the device. A missing measurement is shown as unavailable, never as zero.</p>
            </section>
            <section>
              <h2>Emergency call</h2>
              <p className="ink2">An emergency call opens a video room with that patient so you can speak to them. It does not contact an ambulance, the police, or a hospital emergency department. Someone in a medical emergency needs local emergency services.</p>
            </section>
            <section>
              <h2>Demo</h2>
              <p className="ink2">If the dashboard says it is using demo data, the patients are fictional and nothing is a real clinical record.</p>
            </section>
          </div>
          {onBack ? (
            <button type="button" className="btn" onClick={onBack}>Back to sign-up</button>
          ) : (
            <div className="row wrap">
              <Link to="/signup" className="btn">Back to sign-up</Link>
              <Link to="/login" className="btn ghost">Sign in</Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
