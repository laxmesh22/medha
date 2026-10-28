// Charts follow the dataviz spec: one series per chart (small multiples instead of a legend), 2px lines, >= 8px
// dots with a 2px surface ring, <= 24px bars with a 4px rounded data end, solid hairline grid, value-first tooltips.
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Session } from "../lib/types";
import { fmtDate } from "../lib/stats";

const C = {
  series1: "#0f6e6e", // = --series-1 (SVG attributes do not resolve CSS variables)
  series2: "#0f6e6e", // = --series-2: the design language allows one accent colour
  grid: "#ecece6",
  axis: "#5c5c57",
  surface: "#ffffff",
  ink2: "#5c5c57",
};
const DAY = 86_400_000;
/** Round an axis maximum up so ticks land on clean steps (0 / 4 / 8 / 12 / 16, not 0 / 4 / 8 / 14). */
const niceMax = (m: number) => (m <= 4 ? Math.max(1, m) : Math.ceil(m / 4) * 4);

const axisProps = {
  tick: { fill: C.axis, fontSize: 14 },
  axisLine: { stroke: "#cfcfc8" },
  tickLine: false,
} as const;

function Tip({ active, payload, unit, keyColor, fmt }: {
  active?: boolean; payload?: { value: number; payload: { label: string } }[]; unit: string; keyColor: string;
  fmt?: (v: number) => string;
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0];
  return (
    <div className="tooltip">
      <div className="row">
        <span className="key" style={{ background: keyColor }} />
        <span className="v num">{fmt ? fmt(p.value) : `${p.value}${unit}`}</span>
      </div>
      <div className="k">{p.payload.label}</div>
    </div>
  );
}

/** Peak range of motion per session for one exercise, with the clinician's target as a labelled reference. */
export function RomChart({ series, target, max }: { series: { t: number; peak: number }[]; target: number | null; max: number }) {
  const data = series.map((p) => ({ t: p.t, peak: Math.round(p.peak), label: fmtDate(new Date(p.t).toISOString()) }));
  const top = Math.min(max, Math.ceil((Math.max(target ?? 0, ...data.map((d) => d.peak)) + 15) / 10) * 10);
  return (
    <ResponsiveContainer width="100%" height={190}>
      <LineChart data={data} margin={{ top: 14, right: 96, bottom: 0, left: -12 }}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} {...axisProps}
          tickFormatter={(t: number) => fmtDate(new Date(t).toISOString())} minTickGap={36} />
        <YAxis domain={[0, top]} {...axisProps} tickFormatter={(v: number) => `${v}°`} width={48} />
        {target !== null ? (
          <ReferenceLine y={target} stroke={C.ink2} strokeWidth={1}
            label={{ value: `Target ${target}°`, position: "right", fill: C.ink2, fontSize: 14 }} />
        ) : null}
        <Tooltip content={<Tip unit="°" keyColor="var(--series-1)" />} cursor={{ stroke: C.axis, strokeWidth: 1 }} />
        <Line type="monotone" dataKey="peak" stroke={C.series1} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
          dot={false} activeDot={{ r: 5, fill: C.series1, stroke: C.surface, strokeWidth: 2 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Sessions per day over the last N days vs the planned number per day. */
export function AdherenceChart({ sessions, days, plannedPerDay }: { sessions: Session[]; days: number; plannedPerDay: number }) {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const data = Array.from({ length: days }, (_, i) => {
    const d0 = start.getTime() - (days - 1 - i) * DAY;
    const n = sessions.filter((s) => {
      const t = Date.parse(s.started_at);
      return t >= d0 && t < d0 + DAY;
    }).length;
    return { t: d0, n, label: new Date(d0).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" }) };
  });
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} margin={{ top: 14, right: 104, bottom: 0, left: -18 }} barCategoryGap="22%">
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="t" {...axisProps} tickFormatter={(t: number) => fmtDate(new Date(t).toISOString())} minTickGap={28} />
        <YAxis allowDecimals={false} domain={[0, niceMax(Math.max(plannedPerDay, ...data.map((d) => d.n)))]} tickCount={5}
          {...axisProps} width={44} />
        {plannedPerDay > 0 ? (
          <ReferenceLine y={plannedPerDay} stroke={C.ink2} strokeWidth={1}
            label={{ value: `Planned ${plannedPerDay}/day`, position: "right", fill: C.ink2, fontSize: 14 }} />
        ) : null}
        <Tooltip content={<Tip unit="" keyColor="var(--series-1)" fmt={(v) => `${v} session${v === 1 ? "" : "s"}`} />}
          cursor={{ fill: "rgba(18,114,106,0.06)" }} />
        <Bar dataKey="n" fill={C.series1} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Pain after sessions (0-10, patient-reported), averaged per day. */
export function PainChart({ sessions, stop }: { sessions: Session[]; stop: number | null }) {
  const byDay = new Map<number, number[]>();
  for (const s of sessions) {
    if (s.pain_after === null) continue;
    const d = new Date(s.started_at);
    const t = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12).getTime();
    byDay.set(t, [...(byDay.get(t) ?? []), s.pain_after]);
  }
  const data = [...byDay.entries()].sort((a, b) => a[0] - b[0]).map(([t, v]) => ({
    t, pain: Math.round((v.reduce((x, y) => x + y, 0) / v.length) * 10) / 10, label: `${fmtDate(new Date(t).toISOString())} · day average`,
  }));
  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={data} margin={{ top: 14, right: 104, bottom: 0, left: -18 }}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} {...axisProps}
          tickFormatter={(t: number) => fmtDate(new Date(t).toISOString())} minTickGap={36} />
        <YAxis domain={[0, 10]} ticks={[0, 2, 4, 6, 8, 10]} {...axisProps} width={44} />
        {stop !== null ? (
          <ReferenceLine y={stop} stroke={C.ink2} strokeWidth={1}
            label={{ value: `Stop at ${stop}`, position: "right", fill: C.ink2, fontSize: 14 }} />
        ) : null}
        <Tooltip content={<Tip unit="/10" keyColor="var(--series-2)" />} cursor={{ stroke: C.axis, strokeWidth: 1 }} />
        <Line type="monotone" dataKey="pain" stroke={C.series2} strokeWidth={2} dot={false}
          activeDot={{ r: 5, fill: C.series2, stroke: C.surface, strokeWidth: 2 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
