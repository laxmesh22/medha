import { BookOpen, HeartPulse, LayoutDashboard, LogOut, UserRound, Users } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { AuriLockup, AuriMark } from "./Logo";
import { api } from "../lib/api";
import { useData } from "../lib/store";
import { Avatar } from "./ui";

export function Layout() {
  const { clinician, summaries } = useData();
  const nav = useNavigate();
  const attention = summaries.filter((s) => s.status !== "good").length;
  if (!clinician) return null;
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <AuriLockup size={52} tone="light" />
        </div>
        <nav className="nav">
          <NavLink to="/" end><LayoutDashboard size={18} />Overview</NavLink>
          <NavLink to="/attention"><HeartPulse size={18} />Needs attention{attention ? <span className="count">{attention}</span> : null}</NavLink>
          <NavLink to="/patients"><Users size={18} />Patients<span className="count">{summaries.length}</span></NavLink>
          <NavLink to="/library"><BookOpen size={18} />Exercise library</NavLink>
          <NavLink to="/profile"><UserRound size={18} />Profile & code</NavLink>
        </nav>
        <div className="sidebar-foot">
          <NavLink to="/profile" className="code-chip">
            <div className="label">Your referral code</div>
            <div className="code">{clinician.referral_code}</div>
          </NavLink>
          <div className="me">
            <span className="avatar on-teal">{clinician.full_name.replace(/^Dr\.?\s+/i, "").split(/\s+/).map((w) => w[0]).slice(0, 2).join("")}</span>
            <span className="who">
              {clinician.full_name}
              <small>{clinician.clinic ?? clinician.title}</small>
            </span>
            <button className="icon-btn" style={{ marginLeft: "auto", color: "rgba(245,242,234,0.75)" }} title="Sign out"
              onClick={async () => { await api.signOut(); nav("/login"); }}>
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <main className="main">
        <nav className="mobile-nav" aria-label="Sections">
          <span className="brand-mark"><AuriMark size={24} tone="light" /></span>
          <NavLink to="/" end>Overview</NavLink>
          <NavLink to="/attention">Attention</NavLink>
          <NavLink to="/patients">Patients</NavLink>
          <NavLink to="/library">Library</NavLink>
          <NavLink to="/profile">Code</NavLink>
        </nav>
        <Outlet />
      </main>
    </div>
  );
}

export function TopBar({ children }: { children?: React.ReactNode }) {
  return (
    <div className="topbar">
      {children}
      <span className="grow" />
      {api.mode === "demo" ? <span className="demo-banner">Demo data · fictional patients</span> : null}
    </div>
  );
}

export { Avatar };
