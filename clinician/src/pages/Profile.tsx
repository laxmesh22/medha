import { Check, Copy } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { TopBar } from "../components/Layout";
import { Empty, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { resetDemo } from "../lib/demo";
import { practisingSince } from "../lib/practice";
import { stationMeasured, stationMeasureLabel } from "../lib/station";
import { useData } from "../lib/store";

export function Profile() {
  const { clinician } = useData();
  const [qr, setQr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const code = clinician?.referral_code ?? "";

  useEffect(() => {
    if (!code) return;
    QRCode.toDataURL(code, { width: 220, margin: 1, color: { dark: "#0a4a4f", light: "#ffffff" } }).then(setQr).catch(() => setQr(null));
  }, [code]);

  if (!clinician) return <Empty>Loading…</Empty>;

  const share = `Join me on Auri: open the app, choose "Link my physiotherapist" and enter the code ${code}.`;
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked: the code stays visible to copy by hand */
    }
  };

  return (
    <>
      <TopBar />
      <div className="content">
        <div className="page-head"><div><h1>Profile & referral code</h1><p>Patients use this code to link to you and share their data.</p></div></div>
        <div className="grid grid-3">
          <div className="card card-pad span-2">
            <h2>Your referral code</h2>
            <div className="row wrap" style={{ gap: 28, marginTop: 14, alignItems: "center" }}>
              {qr ? <span className="qr"><img src={qr} width={180} height={180} alt={`QR code for ${code}`} /></span> : null}
              <div className="stack" style={{ gap: 12 }}>
                <div className="big-code">{code}</div>
                <div className="row wrap">
                  <button className="btn" onClick={() => copy(code)}>{copied ? <Check size={16} /> : <Copy size={16} />}{copied ? "Copied" : "Copy code"}</button>
                  <button className="btn ghost" onClick={() => copy(share)}>Copy invite message</button>
                </div>
                <div className="ink2" style={{ fontSize: 14, maxWidth: 440 }}>
                  How it works: the patient signs up in the Auri app, fills in their details, then enters this code (or scans
                  the QR). They agree to share their data with you and appear in your patient list.
                </div>
              </div>
            </div>
          </div>
          <div className="card card-pad">
            <div className="row between" style={{ marginBottom: 14 }}>
              <h2>Profile</h2>
              {clinician.verification_status === "verified" ? <StatusBadge severity="good" label="Licence verified" />
                : clinician.verification_status === "rejected" ? <StatusBadge severity="critical" label="Licence not verified" />
                : <StatusBadge severity="warning" label="Verification pending" />}
            </div>
            <dl className="kv">
              <dt>Name</dt><dd>{clinician.full_name}</dd>
              <dt>Qualification</dt><dd>{[clinician.title, clinician.specialization].filter(Boolean).join(" · ") || "—"}</dd>
              <dt>Clinic</dt><dd>{[clinician.clinic, clinician.city].filter(Boolean).join(", ") || "—"}</dd>
              <dt>Licence number</dt><dd>{clinician.registration_no || "—"}</dd>
              <dt>Council</dt><dd>{clinician.council || "—"}</dd>
              <dt>Practising since</dt><dd>{practisingSince(clinician.years_experience)}</dd>
              <dt>Phone</dt><dd>{clinician.phone || "—"}</dd>
              <dt>Email</dt><dd>{clinician.email || "—"}</dd>
            </dl>
            <p className="muted" style={{ fontSize: 13, margin: "14px 0 0" }}>Taken at sign-up. Ask the Auri team if a licence or clinic name needs correcting.</p>
            {api.mode === "demo" ? (
              <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
                <div className="muted" style={{ fontSize: 13, marginBottom: 8 }}>Demo mode: plans you publish are kept in this browser.</div>
                <button className="btn ghost small" onClick={() => { resetDemo(); window.location.reload(); }}>Reset demo data</button>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </>
  );
}

export function Library() {
  const { exercises } = useData();
  return (
    <>
      <TopBar />
      <div className="content">
        <div className="page-head">
          <div>
            <h1>Exercise library</h1>
            <p>Prescribe these from a patient's care plan. The station measures three of them. The others are home exercises until the coach can run them.</p>
          </div>
        </div>
        <div className="grid grid-2">
          {exercises.map((e) => (
            <div key={e.id} className="card card-pad">
              <div className="row between">
                <h2>{e.name}</h2>
                <span className="chip">{e.metric === "rotation" ? "Measures rotation" : "Measures elevation"}</span>
              </div>
              <div style={{ margin: "8px 0 4px" }}>
                <StatusBadge severity={stationMeasured(e.id) ? "good" : "warning"} label={stationMeasureLabel(e.id)} />
              </div>
              <p className="ink2">{e.description}</p>
              <div className="muted" style={{ fontSize: 13 }}>Default dose: {e.default_sets} × {e.default_reps}{e.default_hold ? `, hold ${e.default_hold} s` : ""}</div>
            </div>
          ))}
        </div>
        <div className="note" style={{ marginTop: 18 }}>
          For the exercises marked "Measured at the station", range of motion comes from body geometry. The coach rejects
          reps with trunk lean, elbow drift or shrugging, so counted reps are clean reps. Home exercises are not scored at the station yet.
        </div>
      </div>
    </>
  );
}
