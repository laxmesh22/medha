import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { useEffect } from "react";
import { BrowserRouter, MemoryRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { DataProvider, useData } from "./lib/store";
import { Login } from "./pages/Auth";
import { Signup } from "./pages/Signup";
import { Overview } from "./pages/Overview";
import { PatientDetail } from "./pages/PatientDetail";
import { Patients } from "./pages/Patients";
import { Library, Profile } from "./pages/Profile";
import "./styles.css";

function Guard() {
  const { loading, email, clinician, error } = useData();
  if (loading) return <div className="empty" style={{ paddingTop: 120 }}>Loading…</div>;
  if (error) return <div className="empty error" style={{ paddingTop: 120 }}>Could not load data: {error}</div>;
  if (!email) return <Navigate to="/login" replace />;
  if (!clinician) return <Navigate to="/signup" replace />;
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
