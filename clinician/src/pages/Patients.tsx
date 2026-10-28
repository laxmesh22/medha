import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { TopBar } from "../components/Layout";
import { Avatar, Empty, Meter, StatusBadge } from "../components/ui";
import { deg, relativeDay, type Severity } from "../lib/stats";
import { useData } from "../lib/store";

const FILTERS: { id: "all" | "attention" | "noplan"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "attention", label: "Needs attention" },
  { id: "noplan", label: "No plan" },
];

const SIDE = { left: "Left", right: "Right", both: "Both" } as const;
const SEX = { female: "F", male: "M", other: "Other", prefer_not_to_say: "—" } as const;

export function Patients() {
  const { summaries, clinician } = useData();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("all");

  const rows = useMemo(() => summaries.filter((s) => {
    if (q && !s.patient.full_name.toLowerCase().includes(q.toLowerCase())) return false;
    if (filter === "attention") return s.status !== "good";
    if (filter === "noplan") return !s.plan;
    return true;
  }), [summaries, q, filter]);

  return (
    <>
      <TopBar>
        <label className="search">
          <Search size={16} className="muted" />
          <input placeholder="Search patients" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search patients" />
        </label>
      </TopBar>
      <div className="content">
        <div className="page-head">
          <div>
            <h1>Patients</h1>
            <p>Patients appear here after they enter your code <b className="num">{clinician?.referral_code}</b> in the Physio Buddy app.</p>
          </div>
          <div className="row">
            {FILTERS.map((f) => (
              <button key={f.id} className={`btn small ${filter === f.id ? "" : "ghost"}`} onClick={() => setFilter(f.id)}>{f.label}</button>
            ))}
          </div>
        </div>
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Patient</th>
                <th>Shoulder</th>
                <th>Plan</th>
                <th>Adherence, 7 days</th>
                <th>Last session</th>
                <th>Forward raise</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const flex = s.rom.flexion;
                const target = s.plan?.items.find((i) => i.exercise_id === "flexion")?.rom_target_deg ?? null;
                const worst = s.alerts.reduce<{ severity: Severity; label: string } | null>((w, a) =>
                  !w || ["good", "warning", "serious", "critical"].indexOf(a.severity) > ["good", "warning", "serious", "critical"].indexOf(w.severity) ? a : w, null);
                return (
                  <tr key={s.patient.id} className="click" onClick={() => nav(`/patients/${s.patient.id}`)}>
                    <td>
                      <div className="person">
                        <Avatar name={s.patient.full_name} />
                        <div>
                          <div className="name">{s.patient.full_name}</div>
                          <div className="meta">{s.age ?? "—"} y · {s.patient.sex ? SEX[s.patient.sex] : "—"}</div>
                        </div>
                      </div>
                    </td>
                    <td>{s.patient.affected_side ? SIDE[s.patient.affected_side] : "—"}</td>
                    <td>{s.plan ? <span>v{s.plan.version} · {s.plan.items.length} exercises</span> : <span className="muted">None yet</span>}</td>
                    <td><Meter value={s.adherence7} /></td>
                    <td>{s.lastSession ? relativeDay(s.lastSession.started_at) : <span className="muted">—</span>}</td>
                    <td className="num">
                      {flex ? <>{deg(flex.latest)}{target ? <span className="muted"> / {target}°</span> : null}</> : <span className="muted">—</span>}
                    </td>
                    <td>{worst ? <StatusBadge severity={worst.severity} label={worst.label} /> : <StatusBadge severity="good" label="On track" />}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 ? <Empty>No patients match.</Empty> : null}
        </div>
      </div>
    </>
  );
}
