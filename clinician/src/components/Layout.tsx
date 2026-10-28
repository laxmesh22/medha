import { BookOpen, LayoutDashboard, LogOut, UserRound, Users } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
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
          <span className="brand-mark" aria-hidden>
            <svg width="20" height="20" viewBox="0 0 32 32"><path d="M7 23 L15 9 L25 23" stroke="currentColor" strokeWidth="3.4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </span>
          <span>
            <div className="brand-name">Physio Buddy</div>
            <div className="brand-sub">Clinician dashboard</div>
          </span>
        </div>
        <nav className="nav">
          <NavLink to="/" end><LayoutDashboard size={18} />Overview{attention ? <span className="count">{attention}</span> : null}</NavLink>
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
            <button className="icon-btn" style={{ marginLeft: "auto", color: "rgba(246,245,240,0.75)" }} title="Sign out"
              onClick={async () => { await api.signOut(); nav("/login"); }}>
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <main className="main">
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
