import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";

const EvidencePage = lazy(() => import("./pages/EvidencePage").then((module) => ({ default: module.EvidencePage })));
const LiveStudioPage = lazy(() => import("./pages/LiveStudioPage").then((module) => ({ default: module.LiveStudioPage })));

export default function App() {
  return (
    <Suspense fallback={<div className="page-state"><span className="loading-ring" /><p>正在载入工作区</p></div>}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/evidence" element={<EvidencePage />} />
          <Route path="/live" element={<LiveStudioPage />} />
          <Route path="*" element={<Navigate to="/evidence" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
