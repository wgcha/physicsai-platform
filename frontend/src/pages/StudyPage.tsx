import { Navigate, useParams } from "react-router-dom";
import type { JobState } from "../api";
import { useApp } from "../app/AppContext";
import { StudyProvider, useStudy } from "../app/StudyContext";
import { STAGES, STAGE_MARK } from "../lib/format";
import { TopBar } from "../shell/TopBar";
import { StageStepper } from "../shell/StageStepper";
import { RightPanel } from "../shell/RightPanel";
import { Stage1 } from "../stages/stage1/Stage1";
import { Stage2 } from "../stages/stage2/Stage2";
import { Stage3 } from "../stages/stage3/Stage3";
import { Stage4 } from "../stages/stage4/Stage4";
import { Stage5 } from "../stages/stage5/Stage5";

export function StudyPage() {
  const { projectId = "", studyId = "", n } = useParams();
  const stage = Number(n ?? 3);
  if (!Number.isInteger(stage) || stage < 1 || stage > 5) return <Navigate to={`/p/${projectId}/s/${studyId}/stage/3`} replace />;
  return (
    <StudyProvider studyId={studyId}>
      <StudyShell projectId={projectId} stage={stage} />
    </StudyProvider>
  );
}

function StudyShell({ projectId, stage }: { projectId: string; stage: number }) {
  const { projects } = useApp();
  const { study } = useStudy();
  const project = projects.find((p) => p.id === projectId);
  const base = `/p/${projectId}/s/${study.id}`;
  const st = STAGES.find((s) => s.n === stage)!;
  const stageStates: Record<number, JobState | null | undefined> = Object.fromEntries(
    [1, 2, 3, 4, 5].map((n) => [n, study.stage_status?.[String(n)]?.latest_state ?? null]),
  );
  return (
    <div className="page">
      <TopBar
        projectId={projectId}
        crumbs={[
          { label: project?.name ?? projectId, to: `/p/${projectId}` },
          { label: study.title, to: `${base}/stage/3` },
          { label: `${STAGE_MARK[stage]} ${st.name}` },
        ]}
      />
      <StageStepper base={base} current={stage} stageStates={stageStates} />
      {study.status === "ARCHIVED" && <div className="warn-box">보관된 Study입니다. 실행할 수 없습니다.</div>}
      <div className="workgrid">
        <main className="workarea" aria-label="작업영역">
          {stage === 1 ? (
            <Stage1 key={study.id} />
          ) : stage === 2 ? (
            <Stage2 key={study.id} />
          ) : stage === 3 ? (
            <Stage3 key={study.id} />
          ) : stage === 4 ? (
            <Stage4 key={study.id} />
          ) : (
            <Stage5 key={study.id} />
          )}
        </main>
        <RightPanel />
      </div>
    </div>
  );
}
