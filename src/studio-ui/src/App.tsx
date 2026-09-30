import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";

const EvidencePage = lazy(() => import("./pages/EvidencePage").then((module) => ({ default: module.EvidencePage })));
const MainlineEvidencePage = lazy(() => import("./pages/MainlineEvidencePage").then((module) => ({ default: module.MainlineEvidencePage })));
const LiveStudioPage = lazy(() => import("./pages/LiveStudioPage").then((module) => ({ default: module.LiveStudioPage })));
const ObservatoryPage = lazy(() => import("./pages/ObservatoryPage").then((module) => ({ default: module.ObservatoryPage })));

export default function App() {
  return (
    <Suspense fallback={<div className="page-state"><span className="loading-ring" /><p>正在载入工作区</p></div>}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/observatory" element={<ObservatoryPage />} />
          <Route path="/evidence" element={<MainlineEvidencePage />} />
          <Route path="/evidence/archive/2026-07-26" element={<EvidencePage />} />
          <Route path="/live" element={<LiveStudioPage />} />
          <Route path="*" element={<Navigate to="/observatory" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
