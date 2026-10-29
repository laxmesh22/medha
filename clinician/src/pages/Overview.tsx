import { Activity, CalendarCheck, ChevronDown, HeartPulse, PhoneCall, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AdherenceChart } from "../components/charts";
import { TopBar } from "../components/Layout";
import { Avatar, Empty, StatTile, StatusBadge } from "../components/ui";
import { JoinCallLink } from "../components/VideoConsult";
import { fmtDateTime, relativeDay, type PatientSummary } from "../lib/stats";
import { useData } from "../lib/store";
import type { Session } from "../lib/types";

/** Shown inside the overview dropdown. A longer list opens its own page. */
const PREVIEW = 3;

function Fold({ title, sub, count, to, children }: {
  title: string; sub?: string; count: number; to: string; children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const big = count > PREVIEW;
  return (
    <div className="card">
      <button type="button" className="card-head fold" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <div>
          <h2>{title}</h2>
          {sub ? <p>{sub}</p> : null}
        </div>
        <ChevronDown size={18} className="chev" />
      </button>
      {open ? (
        <>
          <div className="list" style={{ marginTop: 4 }}>{children}</div>
          {big ? <div className="fold-more"><Link to={to} className="btn ghost small">Open all {count}</Link></div> : null}
        </>
      ) : null}
    </div>
  );
}

export function SessionRow({ session, name }: { session: Session; name: string }) {
  const nav = useNavigate();
  return (
    <div className="list-row click" onClick={() => nav(`/patients/${session.patient_id}?tab=sessions`)}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>{name}</div>
        <div className="muted" style={{ fontSize: 12.5 }}>{fmtDateTime(session.started_at)} · {session.source === "station" ? "Clinic station" : "Home"}</div>
      </div>
      <div style={{ marginLeft: "auto", textAlign: "right", fontSize: 13 }}>
        <div className="num">{session.exercises.reduce((a, e) => a + e.reps_counted, 0)} reps</div>
        <div className="muted num">pain {session.pain_after ?? "—"}/10</div>
      </div>
    </div>
  );
}

export function ActivityRow({ summary }: { summary: PatientSummary }) {
  const nav = useNavigate();
  return (
    <div className="list-row click" onClick={() => nav(`/patients/${summary.patient.id}`)}>
      <Avatar name={summary.patient.full_name} />
      <div style={{ fontWeight: 560, fontSize: 14 }}>{summary.patient.full_name}</div>
      <div className="muted" style={{ marginLeft: "auto", fontSize: 13 }}>
        {summary.lastSession ? relativeDay(summary.lastSession.started_at) : "No sessions"}
      </div>
    </div>
  );
}

export function RecentSessionsPage() {
  const { sessions, patients } = useData();
  const name = (id: string) => patients.find((p) => p.id === id)?.full_name ?? "Patient";
  return (
    <>
      <TopBar />
      <div className="content">
        <div className="page-head">
          <div>
            <h1>Recent sessions</h1>
            <p>Across all your patients</p>
          </div>
          <Link to="/" className="btn ghost small">Back to overview</Link>
        </div>
        <div className="card">
          <div className="list" style={{ marginTop: 6 }}>
            {sessions.length === 0 ? <Empty>No sessions yet.</Empty> : null}
            {sessions.map((s) => <SessionRow key={s.id} session={s} name={name(s.patient_id)} />)}
          </div>
        </div>
      </div>
    </>
  );
}

export function LastActivityPage() {
  const { summaries } = useData();
  return (
    <>
      <TopBar />
      <div className="content">
        <div className="page-head">
          <div>
            <h1>Last activity</h1>
            <p>When each patient last did a session</p>
          </div>
          <Link to="/" className="btn ghost small">Back to overview</Link>
        </div>
        <div className="card">
          <div className="list" style={{ marginTop: 6 }}>
            {summaries.length === 0 ? <Empty>No patients yet.</Empty> : null}
            {summaries.map((s) => <ActivityRow key={s.patient.id} summary={s} />)}
          </div>
        </div>
      </div>
    </>
  );
}

export function Overview() {
  const { clinician, summaries, sessions, patients } = useData();
  const nav = useNavigate();
  const emergency = summaries.filter((s) => s.alerts.some((a) => a.severity === "critical" || a.severity === "serious"));
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
            sub="Linked with your referral code" />
          <StatTile icon={<CalendarCheck size={16} />} label="Sessions, last 7 days" value={week.length}
            sub={`${week.filter((s) => s.source === "station").length} at the clinic station`} />
          <StatTile icon={<Activity size={16} />} label="Average adherence, 7 days" value={avgAdh === null ? "—" : `${Math.round(avgAdh * 100)}%`}
            sub="Sessions done vs prescribed" />
          <StatTile icon={<HeartPulse size={16} />} label="Need attention" value={attention.length}
            sub="Open the list" onClick={() => nav("/attention")} />
        </div>

        <div className="grid split">
          <div className="stack">
            <div className="card">
              <div className="card-head">
                <div>
                  <h2>Needs attention</h2>
                  <p>Pain alerts first, then missed sessions and form issues.</p>
                </div>
                <Link to="/attention" className="btn ghost small">Open</Link>
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
                  <h2>Emergency</h2>
                  <p>High or rising pain. The call reaches the patient, not an ambulance.</p>
                </div>
                <PhoneCall size={18} className="muted" />
              </div>
              <div className="list" style={{ marginTop: 10 }}>
                {emergency.length === 0 ? <Empty>No emergency calls. Patients with high or rising pain show up here.</Empty> : null}
                {emergency.map((s) => (
                  <div key={s.patient.id} className="list-row">
                    <div style={{ minWidth: 0, cursor: "pointer" }} onClick={() => nav(`/patients/${s.patient.id}?tab=video`)}>
                      <div style={{ fontWeight: 600, fontSize: 14 }}>{s.patient.full_name}</div>
                      <div className="muted" style={{ fontSize: 12.5 }}>{s.alerts.filter((a) => a.severity === "critical" || a.severity === "serious").map((a) => a.detail).join(" · ")}</div>
                    </div>
                    <div style={{ marginLeft: "auto" }}>
                      <JoinCallLink patient={s.patient} label="Call now" small />
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <Fold title="Recent sessions" sub="Across all your patients" count={sessions.length} to="/sessions">
              {sessions.length === 0 ? <Empty>No sessions yet.</Empty> : sessions.slice(0, PREVIEW).map((s) => <SessionRow key={s.id} session={s} name={name(s.patient_id)} />)}
            </Fold>
            <Fold title="Last activity" count={summaries.length} to="/activity">
              {summaries.slice(0, PREVIEW).map((s) => <ActivityRow key={s.patient.id} summary={s} />)}
            </Fold>
          </div>
        </div>
      </div>
    </>
  );
}
