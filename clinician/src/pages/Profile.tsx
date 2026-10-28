import { Check, Copy, RefreshCw } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { TopBar } from "../components/Layout";
import { Empty } from "../components/ui";
import { api } from "../lib/api";
import { resetDemo } from "../lib/demo";
import { useData } from "../lib/store";
import { ClinicianForm } from "./Auth";

export function Profile() {
  const { clinician, setClinician } = useData();
  const [qr, setQr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const code = clinician?.referral_code ?? "";

  useEffect(() => {
    if (!code) return;
    QRCode.toDataURL(code, { width: 220, margin: 1, color: { dark: "#0e4f4a", light: "#ffffff" } }).then(setQr).catch(() => setQr(null));
  }, [code]);

  if (!clinician) return <Empty>Loading…</Empty>;

  const share = `Join me on Physio Buddy: open the app, choose "Link my physiotherapist" and enter the code ${code}.`;
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
                  How it works: the patient signs up in the Physio Buddy app, fills in their details, then enters this code (or scans
                  the QR). They agree to share their data with you and appear in your patient list.
                </div>
              </div>
            </div>
            <div style={{ marginTop: 22 }}>
              {!confirm ? (
                <button className="btn danger small" onClick={() => setConfirm(true)}><RefreshCw size={14} />Make a new code</button>
              ) : (
                <div className="warn-note">
                  The old code stops working for new patients. Patients already linked stay linked.
                  <div className="row" style={{ marginTop: 10 }}>
                    <button className="btn small" disabled={busy} onClick={async () => {
                      setBusy(true);
                      try {
                        const c = await api.regenerateReferralCode();
                        setClinician({ ...clinician, referral_code: c });
                      } finally {
                        setBusy(false);
                        setConfirm(false);
                      }
                    }}>Yes, make a new code</button>
                    <button className="btn ghost small" onClick={() => setConfirm(false)}>Cancel</button>
                  </div>
                </div>
              )}
            </div>
          </div>
          <div className="card card-pad">
            <h2 style={{ marginBottom: 14 }}>Profile</h2>
            <ClinicianForm submitLabel="Save profile" />
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
            <p>Movements the clinic station and the straps can measure and count. Prescribe them from a patient's care plan.</p>
          </div>
        </div>
        <div className="grid grid-2">
          {exercises.map((e) => (
            <div key={e.id} className="card card-pad">
              <div className="row between">
                <h2>{e.name}</h2>
                <span className="chip">{e.metric === "rotation" ? "Measures rotation" : "Measures elevation"}</span>
              </div>
              <p className="ink2">{e.description}</p>
              <div className="muted" style={{ fontSize: 13 }}>Default dose: {e.default_sets} × {e.default_reps}{e.default_hold ? `, hold ${e.default_hold} s` : ""}</div>
            </div>
          ))}
        </div>
        <div className="note" style={{ marginTop: 18 }}>
          Range of motion is computed from body geometry (camera skeleton and the arm, forearm and waist straps). The coach rejects
          reps with trunk lean, elbow drift or shrugging, so counted reps are clean reps.
        </div>
      </div>
    </>
  );
}
