import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { getSession } from "./lib/api";
import { LiveProvider } from "./lib/live";
import { Shell } from "./components/Shell";
import { Landing } from "./pages/Landing";
import { Overview } from "./pages/Overview";
import { TwinPage } from "./pages/TwinPage";
import { Households } from "./pages/Households";
import { Incidents } from "./pages/Incidents";
import { Complaints } from "./pages/Complaints";
import { Quality } from "./pages/Quality";
import { AIInsights } from "./pages/AIInsights";
import { Analytics } from "./pages/Analytics";
import { Upkeep } from "./pages/Upkeep";
import { Integration } from "./pages/Integration";
import { Alerts } from "./pages/Alerts";
import { Devices } from "./pages/Devices";
import { About } from "./pages/About";
import { CitizenApp } from "./citizen/CitizenApp";
import { Board } from "./pages/Board";
import { TesterApp } from "./citizen/TesterApp";
import { SamitiApp } from "./citizen/SamitiApp";
import { Planner } from "./pages/Planner";
import { Reconcile } from "./pages/Reconcile";
import { Loader } from "./components/ui";

// the 3D map engine is large; load it only when the GIS page is opened
const MapPage = lazy(() => import("./pages/MapPage").then((m) => ({ default: m.MapPage })));

function Staff() {
  const s = getSession();
  if (!s || s.user.role === "citizen") return <Navigate to="/" replace />;
  return <LiveProvider><Shell /></LiveProvider>;
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/citizen" element={<CitizenApp />} />
        <Route path="/board/:village" element={<Board />} />
        <Route path="/tester" element={<TesterApp />} />
        <Route path="/samiti" element={<SamitiApp />} />
        <Route path="/app" element={<Staff />}>
          <Route index element={<Overview />} />
          <Route path="twin" element={<TwinPage />} />
          <Route path="map" element={<Suspense fallback={<div className="page"><Loader text="Loading the 3D map" /></div>}><MapPage /></Suspense>} />
          <Route path="households" element={<Households />} />
          <Route path="incidents" element={<Incidents />} />
          <Route path="incidents/:id" element={<Incidents />} />
          <Route path="complaints" element={<Complaints />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="quality" element={<Quality />} />
          <Route path="upkeep" element={<Upkeep />} />
          <Route path="ai" element={<AIInsights />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="planner" element={<Planner />} />
          <Route path="reconcile" element={<Reconcile />} />
          <Route path="integration" element={<Integration />} />
          <Route path="devices" element={<Devices />} />
          <Route path="about" element={<About />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
