import { CalendarPlus, Check, Copy, Video, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api } from "../lib/api";
import { calendarDays, fmtDateTime } from "../lib/stats";
import { useData } from "../lib/store";
import type { Patient, VideoCall } from "../lib/types";
import { patientJoinUrl, roomUrl, VIDEO_PROVIDER } from "../lib/video";
import { Empty } from "./ui";

const MIN = 60_000;

/** Scheduled calls from 30 minutes ago onward, soonest first. */
export function upcomingCalls(calls: VideoCall[], patientId?: string, now = Date.now()): VideoCall[] {
  return calls
    .filter((c) => c.status === "scheduled" && c.scheduled_for && Date.parse(c.scheduled_for) > now - 30 * MIN
      && (!patientId || c.patient_id === patientId))
    .sort((a, b) => Date.parse(a.scheduled_for!) - Date.parse(b.scheduled_for!));
}

export function whenLabel(iso: string, now = Date.now()): string {
  const t = Date.parse(iso);
  if (Math.abs(t - now) < 10 * MIN) return "Now";
  const time = new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (t > now && t - now < 90 * MIN) return `In ${Math.round((t - now) / MIN)} min · ${time}`;
  const d = calendarDays(iso, now); // negative = in the future
  const day = d === 0 ? "Today" : d === -1 ? "Tomorrow" : d === 1 ? "Yesterday"
    : new Date(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  return `${day} · ${time}`;
}

/** Opens the patient's room in a new tab and logs the call as started. */
export function JoinCallLink({ patient, call, label = "Start video call", small }: {
  patient: Patient; call?: VideoCall; label?: string; small?: boolean;
}) {
  const { clinician, reload } = useData();
  return (
    <a className={`btn ${small ? "small" : ""}`} href={roomUrl(patient.video_room, clinician?.full_name)} target="_blank" rel="noopener noreferrer"
      onClick={() => { void api.startCall(patient.id, call?.id).then(reload); }}>
      <Video size={small ? 14 : 16} />{label}
    </a>
  );
}

function nextSlot(): string {
  const t = new Date(Date.now() + 60 * MIN);
  t.setMinutes(t.getMinutes() < 30 ? 30 : 60, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}T${pad(t.getHours())}:${pad(t.getMinutes())}`;
}

export function VideoConsult({ patient }: { patient: Patient }) {
  const { calls, reload } = useData();
  const [when, setWhen] = useState(nextSlot);
  const [minutes, setMinutes] = useState(15);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const mine = calls.filter((c) => c.patient_id === patient.id);
  const upcoming = upcomingCalls(mine);
  const past = mine.filter((c) => c.status !== "scheduled" || (c.scheduled_for && !upcoming.includes(c)))
    .sort((a, b) => Date.parse(b.started_at ?? b.scheduled_for ?? b.created_at) - Date.parse(a.started_at ?? a.scheduled_for ?? a.created_at));
  const first = patient.full_name.split(" ")[0];
  const link = patientJoinUrl(patient.video_room);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      document.getElementById("join-link")?.focus();
      (document.getElementById("join-link") as HTMLInputElement | null)?.select();
    }
  };

  const schedule = async (e: FormEvent) => {
    e.preventDefault();
    const t = new Date(when);
    if (Number.isNaN(t.getTime()) || t.getTime() < Date.now() - 5 * MIN) {
      setErr("Pick a time from now onward.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await api.scheduleCall(patient.id, t.toISOString(), minutes, notes);
      setNotes("");
      setWhen(nextSlot());
      await reload();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-3" style={{ alignItems: "start" }}>
      <div className="stack span-2">
        <div className="card card-pad">
          <div className="row between wrap">
            <div>
              <h2>Video consult with {first}</h2>
              <p className="ink2" style={{ margin: "4px 0 0" }}>The call opens in a new tab on {VIDEO_PROVIDER}. {first} joins from the
                Physio Buddy app or the link below; both of you get a camera and microphone check first.</p>
            </div>
          </div>
          <div className="row wrap" style={{ marginTop: 16 }}>
            <JoinCallLink patient={patient} call={upcoming.find((c) => Math.abs(Date.parse(c.scheduled_for!) - Date.now()) < 30 * MIN)} />
            <button className="btn ghost" onClick={copy}>{copied ? <Check size={16} /> : <Copy size={16} />}{copied ? "Copied" : "Copy patient link"}</button>
          </div>
          <div className="field" style={{ marginTop: 14 }}>
            <label htmlFor="join-link">Patient join link (private to this patient)</label>
            <input id="join-link" className="input num" readOnly value={link} onFocus={(e) => e.currentTarget.select()} />
          </div>
        </div>

        <div className="card">
          <div className="card-head"><div><h2>Upcoming</h2><p>{first} sees these in the app with a join button.</p></div></div>
          <div className="list" style={{ marginTop: 10 }}>
            {upcoming.length === 0 ? <Empty>No calls booked.</Empty> : null}
            {upcoming.map((c) => (
              <div key={c.id} className="list-row wrap">
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600 }}>{whenLabel(c.scheduled_for!)}</div>
                  <div className="muted" style={{ fontSize: 13 }}>{c.duration_min} min{c.notes ? ` · ${c.notes}` : ""}</div>
                </div>
                <div className="row" style={{ marginLeft: "auto" }}>
                  {cancelling === c.id ? (
                    <>
                      <span className="muted" style={{ fontSize: 13 }}>Cancel this call?</span>
                      <button className="btn danger small" onClick={async () => { await api.cancelCall(c.id); setCancelling(null); await reload(); }}>Cancel call</button>
                      <button className="btn ghost small" onClick={() => setCancelling(null)}>Keep</button>
                    </>
                  ) : (
                    <>
                      <JoinCallLink patient={patient} call={c} label="Join" small />
                      <button className="icon-btn" title="Cancel call" onClick={() => setCancelling(c.id)}><X size={16} /></button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="card-head"><div><h2>Past calls</h2></div></div>
          <div className="list" style={{ marginTop: 10 }}>
            {past.length === 0 ? <Empty>No calls yet.</Empty> : null}
            {past.map((c) => (
              <div key={c.id} className="list-row">
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 560 }}>{fmtDateTime(c.started_at ?? c.scheduled_for ?? c.created_at)}</div>
                  <div className="muted" style={{ fontSize: 13 }}>{c.notes ?? (c.scheduled_for ? "Booked call" : "Unscheduled call")}</div>
                </div>
                <span className="chip" style={{ marginLeft: "auto" }}>
                  {c.status === "started" ? "Held" : c.status === "cancelled" ? "Cancelled" : "Missed"}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <form className="card card-pad stack" style={{ gap: 14 }} onSubmit={schedule}>
        <div className="row"><CalendarPlus size={18} className="muted" /><h2>Book a call</h2></div>
        <div className="field">
          <label htmlFor="call-when">Date and time</label>
          <input id="call-when" className="input" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="call-len">Length</label>
          <select id="call-len" className="input" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
            {[10, 15, 20, 30, 45].map((m) => <option key={m} value={m}>{m} minutes</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="call-notes">Purpose (the patient sees this)</label>
          <textarea id="call-notes" className="input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)}
            placeholder="e.g. Check technique on the side raise" />
        </div>
        {err ? <div className="error">{err}</div> : null}
        <button className="btn" disabled={busy}>{busy ? "Booking…" : "Book call"}</button>
      </form>
    </div>
  );
}
