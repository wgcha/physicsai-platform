import { BrowserRouter, MemoryRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { AuthGate } from "./AuthGate";
import { NotificationsProvider } from "../hooks/useNotifications";
import { ToastHost } from "../shell/ToastHost";
import { ProjectList } from "../pages/ProjectList";
import { StudyList } from "../pages/StudyList";
import { StudyPage } from "../pages/StudyPage";
import { StudyManage } from "../pages/StudyManage";
import { AdminEnvCheck } from "../pages/AdminEnvCheck";
import { useThemeSync } from "../design/theme";
import { ImportLanding } from "../pages/ImportLanding";

const FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true };

function StudyRedirect() {
  const { projectId, studyId } = useParams();
  return <Navigate to={`/p/${projectId}/s/${studyId}/stage/3`} replace />;
}

export function AppRoutes() {
  useThemeSync();
  return (
    <AuthGate>
      <NotificationsProvider>
        <Routes>
          <Route path="/" element={<ProjectList />} />
          <Route path="/p/:projectId" element={<StudyList />} />
          <Route path="/p/:projectId/s/:studyId" element={<StudyRedirect />} />
          {/* phase3.md §19.3: ⑤ 결과분석(신설, 프런트 전용). 숫자 URL(/stage/4 예측·/stage/5 최적화)은 불변 */}
          <Route path="/p/:projectId/s/:studyId/stage/analysis" element={<StudyPage stage="analysis" />} />
          <Route path="/p/:projectId/s/:studyId/stage/:n" element={<StudyPage />} />
          {/* phase3.md §14.8: ④ 일괄 예측 진행·결과 */}
          <Route path="/p/:projectId/s/:studyId/stage/:n/batch/:batchId" element={<StudyPage />} />
          {/* phase3.md §21.3.11: ④ 공통 FEM 검증(목록·새 검증·상세) */}
          <Route path="/p/:projectId/s/:studyId/stage/:n/verify" element={<StudyPage verify />} />
          <Route path="/p/:projectId/s/:studyId/stage/:n/verify/:fvId" element={<StudyPage verify />} />
          {/* phase3.md §18.10: ⑥ 내장 최적화 결과(URL 숫자 5 유지) */}
          <Route path="/p/:projectId/s/:studyId/stage/:n/surrogate/:optId" element={<StudyPage />} />
          <Route path="/p/:projectId/s/:studyId/manage" element={<StudyManage />} />
          <Route path="/admin/env-check" element={<AdminEnvCheck />} />
          <Route path="/import" element={<ImportLanding />} />
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
