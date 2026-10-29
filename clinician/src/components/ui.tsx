import { AlertTriangle, CheckCircle2, CircleAlert, OctagonAlert } from "lucide-react";
import type { ReactNode } from "react";
import type { Severity } from "../lib/stats";
import { initials } from "../lib/stats";

const SEV_ICON = { good: CheckCircle2, warning: AlertTriangle, serious: CircleAlert, critical: OctagonAlert };

/** Status always ships as icon + label + color, never color alone. */
export function StatusBadge({ severity, label }: { severity: Severity; label: string }) {
  const Icon = SEV_ICON[severity];
  return (
    <span className={`badge ${severity}`}>
      <Icon size={13} strokeWidth={2.4} aria-hidden />
      {label}
    </span>
  );
}

export function Avatar({ name, size }: { name: string; size?: "lg" }) {
  return <span className={`avatar ${size ?? ""}`}>{initials(name)}</span>;
}

export function StatTile({ label, value, sub, icon, onClick }: {
  label: string; value: ReactNode; sub?: ReactNode; icon?: ReactNode; onClick?: () => void;
}) {
  return (
    <div className={`card stat${onClick ? " click" : ""}`} onClick={onClick} role={onClick ? "link" : undefined}
      tabIndex={onClick ? 0 : undefined} onKeyDown={onClick ? (e) => { if (e.key === "Enter") onClick(); } : undefined}>
      <div className="label">
        {icon}
        {label}
      </div>
      <div className="value num">{value}</div>
      {sub ? <div className="sub">{sub}</div> : null}
    </div>
  );
}

export function Meter({ value }: { value: number | null }) {
  if (value === null) return <span className="muted">—</span>;
  const cls = value < 0.5 ? "bad" : value < 0.75 ? "warn" : "";
  return (
    <div className="row" style={{ minWidth: 120 }}>
      <div className={`meter ${cls}`} role="meter" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
        <i style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="num" style={{ fontSize: 13, minWidth: 38, textAlign: "right" }}>
        {Math.round(value * 100)}%
      </span>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
