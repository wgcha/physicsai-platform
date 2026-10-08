import { BrowserRouter, MemoryRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { AuthGate } from "./AuthGate";
import { NotificationsProvider } from "../hooks/useNotifications";
import { ToastHost } from "../shell/ToastHost";
import { ProjectList } from "../pages/ProjectList";
import { StudyList } from "../pages/StudyList";
import { StudyPage } from "../pages/StudyPage";

const FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true };

function StudyRedirect() {
  const { projectId, studyId } = useParams();
  return <Navigate to={`/p/${projectId}/s/${studyId}/stage/3`} replace />;
}

export function AppRoutes() {
  return (
    <AuthGate>
      <NotificationsProvider>
        <Routes>
          <Route path="/" element={<ProjectList />} />
          <Route path="/p/:projectId" element={<StudyList />} />
          <Route path="/p/:projectId/s/:studyId" element={<StudyRedirect />} />
          <Route path="/p/:projectId/s/:studyId/stage/:n" element={<StudyPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <ToastHost />
      </NotificationsProvider>
    </AuthGate>
  );
}

/** 계약 §16.1: basename /physicsai */
export function App() {
  return (
    <BrowserRouter basename="/physicsai" future={FUTURE}>
      <AppRoutes />
    </BrowserRouter>
  );
}

/** 시험용: 메모리 라우터 */
export function TestApp({ path }: { path: string }) {
  return (
    <MemoryRouter initialEntries={[path]} future={FUTURE}>
      <AppRoutes />
    </MemoryRouter>
  );
}
