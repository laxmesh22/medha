import { useNavigate } from "react-router-dom";
import { TopBar } from "../components/Layout";
import { Avatar, Empty, StatusBadge } from "../components/ui";
import { useData } from "../lib/store";

/** Patients who are not on track: pain, missed sessions, form. Opened from the overview. */
export function Attention() {
  const { summaries } = useData();
  const nav = useNavigate();
  const attention = summaries.filter((s) => s.status !== "good");

  return (
    <>
      <TopBar />
      <div className="content">
        <div className="page-head">
          <div>
            <h1>Needs attention</h1>
            <p>Pain alerts first, then missed sessions and form issues.</p>
          </div>
        </div>
        <div className="card">
          <div className="list" style={{ marginTop: 6 }}>
            {attention.length === 0 ? <Empty>Nothing to review. Every patient is on track.</Empty> : null}
            {attention.map((s) => (
              <div key={s.patient.id} className="list-row click" onClick={() => nav(`/patients/${s.patient.id}`)}>
                <Avatar name={s.patient.full_name} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600 }}>{s.patient.full_name}</div>
                  <div className="muted" style={{ fontSize: 13 }}>{s.alerts.map((a) => a.detail).join(" · ")}</div>
                </div>
                <div className="row wrap" style={{ marginLeft: "auto", justifyContent: "flex-end" }}>
                  {s.alerts.map((a) => <StatusBadge key={a.label} severity={a.severity} label={a.label} />)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
