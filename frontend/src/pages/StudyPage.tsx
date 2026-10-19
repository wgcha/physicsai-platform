import { Link, Navigate, useParams } from "react-router-dom";
import { useEffect, useState } from "react";
import type { JobState } from "../api";
import { useApp } from "../app/AppContext";
import { StudyProvider, useStudy } from "../app/StudyContext";
import { stageTitle } from "../lib/format";
import { TopBar } from "../shell/TopBar";
import { StageStepper } from "../shell/StageStepper";
import { RunStatusProvider, StatusChips } from "../shell/RunStatus";
import { Stage1 } from "../stages/stage1/Stage1";
import { Stage2 } from "../stages/stage2/Stage2";
import { Stage3 } from "../stages/stage3/Stage3";
import { Stage4 } from "../stages/stage4/Stage4";
import { StageAnalysis } from "../stages/stageAnalysis/StageAnalysis";
import { Stage5 } from "../stages/stage5/Stage5";
import { BatchResult } from "../stages/stage4/batch/BatchResult";
import { femVerifyApi } from "../api/femVerify";
import { VerifyDetail } from "../stages/stage4/verify/VerifyDetail";
import { VerifyList } from "../stages/stage4/verify/VerifyList";
import { SurrogateResult } from "../stages/stage5/surrogate/SurrogateResult";

/** stage = 고정 단계(App의 /stage/analysis 라우트). 없으면 URL의 :n */
export function StudyPage({ stage: fixed, verify = false }: { stage?: "analysis"; verify?: boolean }) {
  const { projectId = "", studyId = "", n: nParam, batchId, optId, fvId } = useParams();
  const n = fixed ?? nParam;
  // 단계 = URL 끝: 1~5(내부 번호, 5 = 표시 ⑥ 최적화) 또는 analysis(⑤ 결과분석, 프런트 전용 — phase3.md §19.3)
  const path = n ?? "3";
  const num = Number(path);
  const ok = path === "analysis" ? !batchId && !optId : Number.isInteger(num) && num >= 1 && num <= 5 && !(batchId && num !== 4) && !(optId && num !== 5) && !(verify && num !== 4);
  if (!ok) return <Navigate to={`/p/${projectId}/s/${studyId}/stage/3`} replace />;
  return (
    <StudyProvider studyId={studyId}>
      <StudyShell projectId={projectId} stage={path} batchId={batchId ?? null} optId={optId ?? null} verify={verify} fvId={fvId ?? null} />
    </StudyProvider>
  );
}

function StudyShell({ projectId, stage, batchId, optId, verify, fvId }: { projectId: string; stage: string; batchId: string | null; optId: string | null; verify: boolean; fvId: string | null }) {
  const { projects } = useApp();
  const { study } = useStudy();
  const project = projects.find((p) => p.id === projectId);
  // 빵부스러기에 FV 번호(FV-003)를 보이려고 검증 라벨만 따로 읽는다(실패하면 빈 칸)
  const [fvLabel, setFvLabel] = useState<string | null>(null);
  useEffect(() => {
    setFvLabel(null);
    if (!fvId) return;
    let alive = true;
    femVerifyApi.get(fvId).then((f) => alive && setFvLabel(f.label)).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [fvId]);
  const base = `/p/${projectId}/s/${study.id}`;
  const stageStates: Record<number, JobState | null | undefined> = Object.fromEntries(
    [1, 2, 3, 4, 5].map((n) => [n, study.stage_status?.[String(n)]?.latest_state ?? null]),
  );
  return (
    <RunStatusProvider>
      <div className="page">
        <TopBar
          projectId={projectId}
          status={<StatusChips />}
          crumbs={[
            { label: project?.name ?? projectId, to: `/p/${projectId}` },
            { label: study.title, to: `${base}/stage/3` },
            batchId || optId || verify ? { label: stageTitle(stage), to: `${base}/stage/${stage}` } : { label: stageTitle(stage) },
            ...(batchId ? [{ label: "일괄 예측" }] : []),
            ...(optId ? [{ label: "내장 최적화" }] : []),
            ...(verify ? [fvId ? { label: "FEM 검증", to: `${base}/stage/4/verify` } : { label: "FEM 검증" }] : []),
            ...(verify && fvId ? [{ label: fvLabel ?? "…" }] : []),
          ]}
        />
        <div className="stepper-row">
          <StageStepper base={base} current={stage} stageStates={stageStates} />
          <Link className="btn small ghost manage-link" to={`${base}/manage`}>
            Study 관리
          </Link>
        </div>
        {study.status === "ARCHIVED" && (
          <div className="warn-box">
            보관된 Study입니다. 실행할 수 없습니다.
            {study.can_execute && (
              <>
                {" "}
                <Link to={`${base}/manage`}>보관 해제</Link>
              </>
            )}
          </div>
        )}
        <div className="grid workgrid">
          <main className="workarea grid-contents" aria-label="작업영역">
            {stage === "1" ? (
              <Stage1 key={study.id} />
            ) : stage === "2" ? (
              <Stage2 key={study.id} />
            ) : stage === "3" ? (
              <Stage3 key={study.id} />
            ) : stage === "analysis" ? (
              <StageAnalysis key={study.id} />
            ) : stage === "4" && verify ? (
              fvId ? <VerifyDetail key={fvId} fid={fvId} /> : <VerifyList key={study.id} />
            ) : stage === "4" && batchId ? (
              <BatchResult key={batchId} batchId={batchId} />
            ) : stage === "4" ? (
              <Stage4 key={study.id} />
            ) : optId ? (
              <SurrogateResult key={optId} optId={optId} />
            ) : (
              <Stage5 key={study.id} />
            )}
          </main>
        </div>
      </div>
    </RunStatusProvider>
  );
}
