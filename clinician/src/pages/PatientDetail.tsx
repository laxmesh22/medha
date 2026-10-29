import { ArrowLeft, ClipboardList, History, PhoneCall, Plus, Stethoscope, Trash2, TrendingUp, Table2 } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { AdherenceChart, PainChart, RomChart } from "../components/charts";
import { TopBar } from "../components/Layout";
import { Avatar, Empty, Meter, StatTile, StatusBadge } from "../components/ui";
import { stationMeasured, stationMeasureLabel } from "../lib/station";
import { JoinCallLink, upcomingCalls, VideoConsult, whenLabel } from "../components/VideoConsult";
import { api } from "../lib/api";
import { deg, FLAG_LABELS, fmtDate, fmtDateTime, pct, relativeDay, type PatientSummary } from "../lib/stats";
import { useData } from "../lib/store";
import type { Exercise, PlanItem } from "../lib/types";

const TABS = [
  { id: "progress", label: "Progress", icon: TrendingUp },
  { id: "plan", label: "Care plan", icon: ClipboardList },
  { id: "sessions", label: "Sessions", icon: Table2 },
  { id: "medical", label: "Medical info", icon: Stethoscope },
  { id: "video", label: "Emergency", icon: PhoneCall },
] as const;
type TabId = (typeof TABS)[number]["id"];

export function PatientDetail() {
  const { id } = useParams();
  const { summaries, calls } = useData();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as TabId) || "progress";
  const s = summaries.find((x) => x.patient.id === id);
  if (!s) {
    return (
      <>
        <TopBar />
        <div className="content"><Empty>Patient not found, or not linked to you.</Empty></div>
      </>
    );
  }
  const p = s.patient;
  const next = upcomingCalls(calls, p.id)[0];
  return (
    <>
      <TopBar>
        <Link to="/patients" className="btn ghost small"><ArrowLeft size={15} />Patients</Link>
      </TopBar>
      <div className="content">
        <div className="card card-pad" style={{ marginBottom: 20 }}>
          <div className="row wrap" style={{ gap: 18 }}>
            <Avatar name={p.full_name} size="lg" />
            <div style={{ minWidth: 0 }}>
              <h1>{p.full_name}</h1>
              <div className="ink2" style={{ marginTop: 4 }}>
                {s.age ?? "—"} years · {p.sex ?? "—"} · {p.affected_side ? `${p.affected_side} shoulder` : "side not set"} · {p.diagnosis ?? "No diagnosis recorded"}
              </div>
              <div className="muted" style={{ marginTop: 2, fontSize: 13 }}>Linked {fmtDate(p.consent_at)} · {p.phone ?? "no phone"}</div>
            </div>
            <div className="stack" style={{ marginLeft: "auto", gap: 10, alignItems: "flex-end" }}>
              <div className="row wrap" style={{ justifyContent: "flex-end" }}>
                {s.alerts.length ? s.alerts.map((a) => <StatusBadge key={a.label} severity={a.severity} label={a.label} />)
                  : <StatusBadge severity="good" label="On track" />}
              </div>
              <div className="row wrap" style={{ justifyContent: "flex-end" }}>
                {next ? <button className="chip" style={{ border: 0, cursor: "pointer" }} onClick={() => setParams({ tab: "video" })}>
                  <PhoneCall size={13} />Follow-up: {whenLabel(next.scheduled_for!)}</button> : null}
                <JoinCallLink patient={p} call={next && Math.abs(Date.parse(next.scheduled_for!) - Date.now()) < 1_800_000 ? next : undefined}
                  label="Emergency call" small />
              </div>
            </div>
          </div>
        </div>

        <div className="tabs" role="tablist">
          {TABS.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} className={`tab ${tab === t.id ? "active" : ""}`}
              onClick={() => setParams({ tab: t.id })}>
              <t.icon size={16} />{t.label}
            </button>
          ))}
        </div>

        {tab === "progress" ? <Progress s={s} onPlan={() => setParams({ tab: "plan" })} /> : null}
        {tab === "plan" ? <Plan s={s} /> : null}
        {tab === "sessions" ? <Sessions s={s} /> : null}
        {tab === "medical" ? <Medical s={s} /> : null}
        {tab === "video" ? (
          <div className="stack">
            <VideoConsult patient={p} />
            <div className="muted" style={{ fontSize: 13 }}>Text messaging is not part of this release{p.phone ? <>; the patient's phone is <b>{p.phone}</b></> : null}.</div>
          </div>
        ) : null}
      </div>
    </>
  );
}

function Progress({ s, onPlan }: { s: PatientSummary; onPlan: () => void }) {
  const { exerciseName, exercises } = useData();
  if (!s.plan) {
    return (
      <div className="card card-pad">
        <h2>Set the first exercises</h2>
        <p className="ink2">Publish a plan and the patient's sessions, range and pain show up here.</p>
        {s.lastSession ? <p className="ink2">Last session {relativeDay(s.lastSession.started_at)}.</p> : null}
        <button className="btn" onClick={onPlan}><Plus size={16} />Prescribe exercises</button>
      </div>
    );
  }
  const painDelta = s.painNow !== null && s.painPrev !== null ? s.painNow - s.painPrev : null;
  const flags = new Map<string, number>();
  for (const sess of s.sessions.filter((x) => Date.now() - Date.parse(x.started_at) < 14 * 86_400_000))
    for (const e of sess.exercises) for (const f of e.flags) flags.set(f, (flags.get(f) ?? 0) + 1);
  const perDay = Math.max(...s.plan.items.map((i) => i.times_per_day));
  const metric = (id: string) => exercises.find((e) => e.id === id)?.metric ?? "elevation";

  return (
    <div className="stack">
      <div className="grid grid-4">
        <StatTile label="Adherence, 7 days" value={pct(s.adherence7)} sub={`${s.sessions7} of ${s.planned7} planned sessions`} />
        <StatTile label="Last session" value={s.lastSession ? relativeDay(s.lastSession.started_at) : "—"}
          sub={s.lastSession ? fmtDateTime(s.lastSession.started_at) : "No sessions yet"} />
        <StatTile label="Pain after sessions, 7 days" value={s.painNow === null ? "—" : `${s.painNow.toFixed(1)}/10`}
          sub={painDelta === null ? "Not enough data" : (
            <span className={painDelta > 0.4 ? "delta-bad" : painDelta < -0.4 ? "delta-good" : ""}>
              {painDelta > 0 ? "▲" : painDelta < 0 ? "▼" : "■"} {Math.abs(painDelta).toFixed(1)} vs previous week
            </span>)} />
        <StatTile label="Reps with good form, 7 days" value={pct(s.formQuality)} sub="Accepted by the coach (no compensation)" />
      </div>

      <div>
        <h2 style={{ marginBottom: 4 }}>Range of motion</h2>
        <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>Best rep of each day, measured by the camera and straps (geometry, not typed in).</p>
        <div className="grid grid-2">
          {s.plan.items.map((it) => {
            const measured = stationMeasured(it.exercise_id);
            const r = measured ? s.rom[it.exercise_id] : undefined;
            const gain = r && r.latest !== null && r.first !== null ? r.latest - r.first : null;
            return (
              <div key={it.exercise_id} className="card chart-card">
                <div className="chart-title">
                  <div>
                    <h3>{exerciseName(it.exercise_id)}</h3>
                    <div className="muted" style={{ fontSize: 13 }}>
                      {measured ? (
                        gain === null ? "No data yet" : <><span className={gain >= 0 ? "delta-good" : "delta-bad"}>{gain >= 0 ? "▲" : "▼"} {Math.abs(Math.round(gain))}°</span> since the first session</>
                      ) : stationMeasureLabel(it.exercise_id)}
                    </div>
                  </div>
                  <span className="big num">{measured ? deg(r?.latest ?? null) : "—"}</span>
                </div>
                {measured
                  ? (r?.series.length ? <RomChart series={r.series} target={it.rom_target_deg} max={metric(it.exercise_id) === "rotation" ? 90 : 180} />
                    : <Empty>No measured reps yet.</Empty>)
                  : <Empty>Not measured by the station yet</Empty>}
              </div>
            );
          })}
        </div>
      </div>

      <div className="grid grid-2">
        <div className="card chart-card">
          <div className="chart-title">
            <div><h3>Sessions per day</h3><div className="muted" style={{ fontSize: 13 }}>Last 28 days</div></div>
            <span className="big num">{s.sessions.filter((x) => Date.now() - Date.parse(x.started_at) < 28 * 86_400_000).length}</span>
          </div>
          <AdherenceChart sessions={s.sessions} days={28} plannedPerDay={perDay} />
        </div>
        <div className="card chart-card">
          <div className="chart-title">
            <div><h3>Pain after sessions</h3><div className="muted" style={{ fontSize: 13 }}>Daily average · 0 = none, 10 = worst · patient-reported</div></div>
            <span className="big num">{s.sessions[0]?.pain_after ?? "—"}/10</span>
          </div>
          <PainChart sessions={s.sessions} stop={Math.min(...s.plan.items.map((i) => i.pain_stop))} />
        </div>
      </div>

      <div className="card">
        <div className="card-head"><div><h2>Form flags, last 14 days</h2><p>Compensations the coach caught. Each rejected rep is not counted.</p></div></div>
        <div className="list" style={{ marginTop: 10 }}>
          {[...flags.entries()].sort((a, b) => b[1] - a[1]).map(([f, n]) => (
            <div key={f} className="list-row">
              <span style={{ fontWeight: 560 }}>{FLAG_LABELS[f] ?? f}</span>
              <span className="muted" style={{ marginLeft: "auto" }}>{n} exercise set{n === 1 ? "" : "s"}</span>
            </div>
          ))}
          {flags.size === 0 ? <Empty>No compensations flagged.</Empty> : null}
        </div>
      </div>
    </div>
  );
}

function Plan({ s }: { s: PatientSummary }) {
  const { plans, exercises, exerciseName, reload } = useData();
  const history = plans.filter((p) => p.patient_id === s.patient.id);
  const [editing, setEditing] = useState(!s.plan);
  if (editing) return <PlanEditor s={s} exercises={exercises} onDone={async () => { await reload(); setEditing(false); }} onCancel={s.plan ? () => setEditing(false) : undefined} />;
  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <div>
            <h2>Current plan · version {s.plan!.version}</h2>
            <p>Published {fmtDateTime(s.plan!.created_at)}. The patient's app and the clinic station follow this plan.</p>
          </div>
          <button className="btn" onClick={() => setEditing(true)}>Edit plan</button>
        </div>
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table className="table">
            <thead><tr><th>Exercise</th><th>Dose</th><th>Frequency</th><th>Range target</th><th>Stop if pain ≥</th><th>Notes</th></tr></thead>
            <tbody>
              {s.plan!.items.map((i) => (
                <tr key={i.exercise_id}>
                  <td style={{ fontWeight: 600 }}>{exerciseName(i.exercise_id)}</td>
                  <td className="num">{i.sets} × {i.reps}{i.hold_s ? `, hold ${i.hold_s} s` : ""}</td>
                  <td className="num">{i.times_per_day}× a day, {i.days_per_week === 7 ? "every day" : `${i.days_per_week} days a week`}</td>
                  <td className="num">{i.rom_target_deg === null ? <span className="muted">—</span> : `${i.rom_target_deg}°`}</td>
                  <td className="num">{i.pain_stop}/10</td>
                  <td className="ink2">{i.notes ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {s.plan!.notes ? <div className="card-pad" style={{ paddingTop: 12 }}><div className="note">{s.plan!.notes}</div></div> : null}
      </div>
      <div className="card">
        <div className="card-head"><div><h2>History</h2><p>Every change is a new version; older versions are kept.</p></div><History size={18} className="muted" /></div>
        <div className="list" style={{ marginTop: 10 }}>
          {history.map((h) => (
            <div key={h.id} className="list-row">
              <b>v{h.version}</b>
              <span className="ink2">{h.items.map((i) => `${exerciseName(i.exercise_id)} ${i.sets}×${i.reps}`).join(" · ")}</span>
              <span className="muted" style={{ marginLeft: "auto", whiteSpace: "nowrap" }}>{fmtDate(h.created_at)}</span>
              {h.status === "active" ? <span className="chip">Active</span> : null}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function PlanEditor({ s, exercises, onDone, onCancel }: { s: PatientSummary; exercises: Exercise[]; onDone: () => void; onCancel?: () => void }) {
  const fresh = (e: Exercise): PlanItem => ({
    exercise_id: e.id, sets: e.default_sets, reps: e.default_reps, hold_s: e.default_hold, times_per_day: 2, days_per_week: 7,
    rom_target_deg: null, pain_stop: 6, notes: null,
  });
  const [items, setItems] = useState<PlanItem[]>(s.plan?.items.map((i) => ({ ...i })) ?? exercises.slice(0, 3).map(fresh));
  const [notes, setNotes] = useState(s.plan?.notes ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const upd = (k: number, patch: Partial<PlanItem>) => setItems(items.map((it, i) => (i === k ? { ...it, ...patch } : it)));
  const unused = exercises.filter((e) => !items.some((i) => i.exercise_id === e.id));
  const num = (v: string, lo: number, hi: number) => Math.max(lo, Math.min(hi, Math.round(Number(v) || lo)));

  const publish = async () => {
    if (!items.length) { setErr("Add at least one exercise."); return; }
    setBusy(true);
    setErr(null);
    try {
      await api.publishPlan(s.patient.id, notes, items);
      await onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>{s.plan ? `Edit plan (publishes version ${s.plan.version + 1})` : "Prescribe exercises"}</h2>
          <p>Targets and progression are your call: the app never raises them on its own.</p>
        </div>
      </div>
      <div className="table-wrap" style={{ padding: "10px 14px 0" }}>
        <table className="table plan-table">
          <thead><tr><th style={{ minWidth: 200 }}>Exercise</th><th>Sets</th><th>Reps</th><th>Hold (s)</th><th>Per day</th><th>Days/week</th><th>Range target (°)</th><th>Stop if pain ≥</th><th style={{ minWidth: 160 }}>Notes</th><th /></tr></thead>
          <tbody>
            {items.map((it, k) => (
              <tr key={k}>
                <td>
                  <select className="input" value={it.exercise_id} onChange={(e) => upd(k, { exercise_id: e.target.value })} aria-label="Exercise">
                    {exercises.filter((e) => e.id === it.exercise_id || !items.some((i) => i.exercise_id === e.id)).map((e) => (
                      <option key={e.id} value={e.id}>{e.name} — {stationMeasureLabel(e.id)}</option>
                    ))}
                  </select>
                  <div style={{ marginTop: 6 }}>
                    <StatusBadge severity={stationMeasured(it.exercise_id) ? "good" : "warning"} label={stationMeasureLabel(it.exercise_id)} />
                  </div>
                </td>
                <td><input className="input num" type="number" min={1} max={10} value={it.sets} onChange={(e) => upd(k, { sets: num(e.target.value, 1, 10) })} aria-label="Sets" /></td>
                <td><input className="input num" type="number" min={1} max={50} value={it.reps} onChange={(e) => upd(k, { reps: num(e.target.value, 1, 50) })} aria-label="Reps" /></td>
                <td><input className="input num" type="number" min={0} max={120} value={it.hold_s} onChange={(e) => upd(k, { hold_s: num(e.target.value, 0, 120) })} aria-label="Hold seconds" /></td>
                <td><input className="input num" type="number" min={1} max={6} value={it.times_per_day} onChange={(e) => upd(k, { times_per_day: num(e.target.value, 1, 6) })} aria-label="Times per day" /></td>
                <td><input className="input num" type="number" min={1} max={7} value={it.days_per_week} onChange={(e) => upd(k, { days_per_week: num(e.target.value, 1, 7) })} aria-label="Days per week" /></td>
                <td><input className="input num" type="number" min={0} max={180} placeholder="none" value={it.rom_target_deg ?? ""}
                  onChange={(e) => upd(k, { rom_target_deg: e.target.value === "" ? null : num(e.target.value, 0, 180) })} aria-label="Range target" /></td>
                <td><input className="input num" type="number" min={1} max={10} value={it.pain_stop} onChange={(e) => upd(k, { pain_stop: num(e.target.value, 1, 10) })} aria-label="Pain stop" /></td>
                <td><input className="input" value={it.notes ?? ""} onChange={(e) => upd(k, { notes: e.target.value || null })} aria-label="Notes" /></td>
                <td><button className="icon-btn" title="Remove" onClick={() => setItems(items.filter((_, i) => i !== k))}><Trash2 size={16} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card-pad stack" style={{ gap: 14 }}>
        <div>
          <button className="btn ghost small" disabled={!unused.length} onClick={() => unused.length && setItems([...items, fresh(unused[0])])}>
            <Plus size={15} />Add exercise
          </button>
        </div>
        <div className="field">
          <label htmlFor="pnotes">Instructions for the patient</label>
          <textarea id="pnotes" className="input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)}
            placeholder="e.g. Warm up first. Stay below the pain-stop level; hold gently at the end of range." />
        </div>
        {err ? <div className="error">{err}</div> : null}
        <div className="row">
          <button className="btn" disabled={busy} onClick={publish}>{busy ? "Publishing…" : s.plan ? `Publish version ${s.plan.version + 1}` : "Publish plan"}</button>
          {onCancel ? <button className="btn ghost" onClick={onCancel}>Cancel</button> : null}
        </div>
      </div>
    </div>
  );
}

function Sessions({ s }: { s: PatientSummary }) {
  const { exerciseName } = useData();
  if (!s.sessions.length) return <div className="card"><Empty>No sessions yet.</Empty></div>;
  return (
    <div className="card table-wrap">
      <table className="table">
        <thead><tr><th>When</th><th>Where</th><th>Duration</th><th>Exercises (peak angle, reps accepted)</th><th>Pain</th><th>Flags</th></tr></thead>
        <tbody>
          {s.sessions.map((x) => {
            const fl = [...new Set(x.exercises.flatMap((e) => e.flags))];
            return (
              <tr key={x.id}>
                <td className="num" style={{ whiteSpace: "nowrap" }}>{fmtDateTime(x.started_at)}</td>
                <td>{x.source === "station" ? "Clinic station" : "Home"}</td>
                <td className="num">{Math.round(x.duration_s / 60)} min</td>
                <td className="ink2" style={{ fontSize: 13.5 }}>
                  {x.exercises.map((e) => (
                    <div key={e.exercise_id}>
                      {exerciseName(e.exercise_id)}: <b className="num">{deg(e.peak_deg)}</b>, {e.reps_counted}/{e.reps_counted + e.reps_rejected} reps
                    </div>
                  ))}
                </td>
                <td className="num" style={{ whiteSpace: "nowrap" }}>{x.pain_before ?? "—"} → {x.pain_after ?? "—"}</td>
                <td>{fl.length ? <div className="row wrap" style={{ gap: 6 }}>{fl.map((f) => <span key={f} className="chip">{FLAG_LABELS[f] ?? f}</span>)}</div> : <span className="muted">—</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Medical({ s }: { s: PatientSummary }) {
  const p = s.patient;
  return (
    <div className="grid grid-2">
      <div className="card card-pad">
        <h2 style={{ marginBottom: 14 }}>Patient details</h2>
        <dl className="kv">
          <dt>Date of birth</dt><dd>{p.date_of_birth ? `${fmtDate(p.date_of_birth)} ${new Date(p.date_of_birth).getFullYear()} (${s.age} y)` : "—"}</dd>
          <dt>Sex</dt><dd>{p.sex ?? "—"}</dd>
          <dt>Phone</dt><dd>{p.phone ?? "—"}</dd>
          <dt>Affected shoulder</dt><dd>{p.affected_side ?? "—"}</dd>
          <dt>Dominant hand</dt><dd>{p.dominant_side ?? "—"}</dd>
          <dt>Shared with you</dt><dd>{fmtDateTime(p.consent_at)} (patient consent)</dd>
        </dl>
      </div>
      <div className="card card-pad">
        <h2 style={{ marginBottom: 14 }}>Clinical</h2>
        <dl className="kv">
          <dt>Diagnosis</dt><dd>{p.diagnosis ?? "—"}</dd>
          <dt>Symptom onset</dt><dd>{p.symptom_onset ? `${fmtDate(p.symptom_onset)} ${new Date(p.symptom_onset).getFullYear()}` : "—"}</dd>
          <dt>Conditions</dt><dd>{p.conditions.length ? <div className="row wrap" style={{ gap: 6 }}>{p.conditions.map((c) => <span key={c} className="chip">{c}</span>)}</div> : "None reported"}</dd>
          <dt>Medications</dt><dd>{p.medications ?? "—"}</dd>
          <dt>Notes</dt><dd>{p.notes ?? "—"}</dd>
        </dl>
      </div>
      <div className="card card-pad span-2">
        <div className="row between wrap">
          <div>
            <h3>Adherence this week</h3>
            <p className="muted" style={{ margin: "2px 0 0", fontSize: 13 }}>{s.sessions7} of {s.planned7} planned sessions</p>
          </div>
          <div style={{ width: 260 }}><Meter value={s.adherence7} /></div>
        </div>
      </div>
    </div>
  );
}
