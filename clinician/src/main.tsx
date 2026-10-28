import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { useEffect } from "react";
import { BrowserRouter, MemoryRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { api } from "./lib/api";
import { DataProvider, useData } from "./lib/store";
import { Login } from "./pages/Auth";
import { Signup } from "./pages/Signup";
import { Overview } from "./pages/Overview";
import { PatientDetail } from "./pages/PatientDetail";
import { Patients } from "./pages/Patients";
import { Library, Profile } from "./pages/Profile";
import "./styles.css";

/** Plain-language reason for a failed load; the raw message stays visible for whoever sets up the backend. */
function explain(error: string): string {
  if (/jwt|jws|key|token|401|role/i.test(error)) {
    return "The database did not accept your sign-in. Check Supabase Third-party Auth (Auth0) and the Auth0 post-login Action that adds role = authenticated.";
  }
  if (/fetch|network/i.test(error)) return "The database could not be reached. Check your internet connection and try again.";
  return "Something went wrong while loading your dashboard.";
}

function Guard() {
  const { loading, email, clinician, error, reload } = useData();
  if (loading) return <div className="empty" style={{ paddingTop: 120 }}>Loading…</div>;
  if (error) {
    return (
      <div className="auth-form" style={{ minHeight: "100vh" }}>
        <div className="auth-card">
          <h1>Could not load your dashboard</h1>
          <div className="alert">{explain(error)}</div>
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>Details: {error}</p>
          <div className="row">
            <button className="btn" onClick={() => void reload()}>Try again</button>
            <button className="btn ghost" onClick={async () => { await api.signOut(); window.location.assign("/login"); }}>Sign out</button>
          </div>
        </div>
      </div>
    );
  }
  if (!email) return <Navigate to="/login" replace />;
  if (!clinician) return <Navigate to="/signup" replace state={{ noAccount: true }} />;
  return <Layout />;
}

/** After an Auth0 / Google redirect, continue where the doctor was going (e.g. back to sign-up). */
function RedirectHandler() {
  const { redirectTo, clearRedirect } = useData();
  const nav = useNavigate();
  useEffect(() => {
    if (redirectTo) {
      nav(redirectTo, { replace: true });
      clearRedirect();
    }
  }, [redirectTo, nav, clearRedirect]);
  return null;
}

// The shared preview runs inside a host frame where path routes do not survive a reload: keep routes in memory there.
const Router = import.meta.env.VITE_ROUTER === "memory" ? MemoryRouter : BrowserRouter;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DataProvider>
      <Router>
        <RedirectHandler />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/onboarding" element={<Navigate to="/signup" replace />} />
          <Route element={<Guard />}>
            <Route index element={<Overview />} />
            <Route path="patients" element={<Patients />} />
            <Route path="patients/:id" element={<PatientDetail />} />
            <Route path="library" element={<Library />} />
            <Route path="profile" element={<Profile />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </DataProvider>
  </StrictMode>,
);
