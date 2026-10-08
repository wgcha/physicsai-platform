import { Navigate, useParams } from "react-router-dom";
import type { JobState } from "../api";
import { useApp } from "../app/AppContext";
import { StudyProvider, useStudy } from "../app/StudyContext";
import { STAGES, STAGE_MARK } from "../lib/format";
import { TopBar } from "../shell/TopBar";
import { DeferredStageNotice, StageStepper } from "../shell/StageStepper";
import { RightPanel } from "../shell/RightPanel";
import { Stage3 } from "../stages/stage3/Stage3";
import { Stage4 } from "../stages/stage4/Stage4";

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
  const stageStates: Record<number, JobState | null | undefined> = {
    3: (study.stage_status?.["3"]?.last_job_state as JobState | undefined) ?? null,
    4: (study.stage_status?.["4"]?.last_job_state as JobState | undefined) ?? null,
  };
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
          {stage === 3 ? <Stage3 key={study.id} /> : stage === 4 ? <Stage4 key={study.id} /> : <DeferredStageNotice n={stage} />}
        </main>
        <RightPanel />
      </div>
    </div>
  );
}
