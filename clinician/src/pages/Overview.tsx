import { Activity, CalendarCheck, HeartPulse, Users } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { AdherenceChart } from "../components/charts";
import { TopBar } from "../components/Layout";
import { Avatar, Empty, StatTile, StatusBadge } from "../components/ui";
import { fmtDateTime, relativeDay } from "../lib/stats";
import { useData } from "../lib/store";

export function Overview() {
  const { clinician, summaries, sessions, patients } = useData();
  const nav = useNavigate();
  const now = Date.now();
  const week = sessions.filter((s) => now - Date.parse(s.started_at) < 7 * 86_400_000);
  const withPlan = summaries.filter((s) => s.adherence7 !== null);
  const avgAdh = withPlan.length ? withPlan.reduce((a, s) => a + (s.adherence7 ?? 0), 0) / withPlan.length : null;
  const attention = summaries.filter((s) => s.status !== "good");
  const name = (id: string) => patients.find((p) => p.id === id)?.full_name ?? "Patient";
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  return (
    <>
      <TopBar />
      <div className="content">
        <div className="page-head">
          <div>
            <h1>{greet}, {clinician?.full_name.split(/\s+/).slice(0, 2).join(" ")}</h1>
            <p>{attention.length ? `${attention.length} patient${attention.length > 1 ? "s" : ""} need${attention.length > 1 ? "" : "s"} your attention today.` : "All patients are on track."}</p>
          </div>
        </div>

        <div className="grid grid-4" style={{ marginBottom: 18 }}>
          <StatTile icon={<Users size={16} />} label="Active patients" value={summaries.length}
            sub={`${summaries.filter((s) => !s.plan).length} waiting for a plan`} />
          <StatTile icon={<CalendarCheck size={16} />} label="Sessions, last 7 days" value={week.length}
            sub={`${week.filter((s) => s.source === "station").length} at the clinic station`} />
          <StatTile icon={<Activity size={16} />} label="Average adherence, 7 days" value={avgAdh === null ? "—" : `${Math.round(avgAdh * 100)}%`}
            sub="Sessions done vs prescribed" />
          <StatTile icon={<HeartPulse size={16} />} label="Need attention" value={attention.length}
            sub={`${attention.filter((s) => s.status === "critical" || s.status === "serious").length} with pain alerts`} />
        </div>

        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)", alignItems: "start" }}>
          <div className="stack">
            <div className="card">
              <div className="card-head">
                <div>
                  <h2>Needs attention</h2>
                  <p>Pain alerts first, then missed sessions, form issues and patients without a plan.</p>
                </div>
              </div>
              <div className="list" style={{ marginTop: 10 }}>
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
            <div className="card chart-card">
              <div className="chart-title">
                <div>
                  <h2>Sessions per day, all patients</h2>
                  <p className="muted" style={{ margin: "2px 0 0", fontSize: 13 }}>Last 14 days</p>
                </div>
                <span className="big num">{sessions.filter((s) => now - Date.parse(s.started_at) < 14 * 86_400_000).length}</span>
              </div>
              <AdherenceChart sessions={sessions} days={14} plannedPerDay={0} />
            </div>
          </div>
          <div className="stack">
            <div className="card">
              <div className="card-head">
                <div>
                  <h2>Recent sessions</h2>
                  <p>Across all your patients</p>
                </div>
              </div>
              <div className="list" style={{ marginTop: 10 }}>
                {sessions.slice(0, 7).map((s) => (
                  <div key={s.id} className="list-row click" onClick={() => nav(`/patients/${s.patient_id}?tab=sessions`)}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 14 }}>{name(s.patient_id)}</div>
                      <div className="muted" style={{ fontSize: 12.5 }}>{fmtDateTime(s.started_at)} · {s.source === "station" ? "Clinic station" : "Home"}</div>
                    </div>
                    <div style={{ marginLeft: "auto", textAlign: "right", fontSize: 13 }}>
                      <div className="num">{s.exercises.reduce((a, e) => a + e.reps_counted, 0)} reps</div>
                      <div className="muted num">pain {s.pain_after ?? "—"}/10</div>
                    </div>
                  </div>
                ))}
                {sessions.length === 0 ? <Empty>No sessions yet.</Empty> : null}
              </div>
            </div>
            <div className="card">
              <div className="card-head"><h2>Last activity</h2></div>
              <div className="list" style={{ marginTop: 10 }}>
                {summaries.map((s) => (
                  <div key={s.patient.id} className="list-row click" onClick={() => nav(`/patients/${s.patient.id}`)}>
                    <Avatar name={s.patient.full_name} />
                    <div style={{ fontWeight: 560, fontSize: 14 }}>{s.patient.full_name}</div>
                    <div className="muted" style={{ marginLeft: "auto", fontSize: 13 }}>
                      {s.lastSession ? relativeDay(s.lastSession.started_at) : "No sessions"}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
