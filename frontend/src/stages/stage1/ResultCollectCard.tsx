import { useEffect, useState } from "react";
import { useApp } from "../../app/AppContext";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Card, RunAction } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { FeatureGate } from "../../components/FeatureGate";
import { useTrain } from "./TrainContext";
import { DoePicker } from "./DoePicker";

// ---------------------------------------------------------------- ①-5
const COLLECT_TEXT: Record<string, string> = {
  in_place: "PBS 결과 폴더에서 자동 회수(in_place)",
  shared_folder: "공유 폴더에서 Study로 자동 복사(shared_folder)",
  drive: "네트워크 드라이브에서 Study로 자동 복사(drive)",
};

export function ResultCollectCard() {
  const { status } = useApp();
  const { study } = useStudy();
  const { doe, runs, reloadRuns } = useTrain();
  const canExec = useCanExecute();
  const imp = useJobRunner("TD_RESULT_IMPORT", () => void reloadRuns());
  const [path, setPath] = useState("");
  const [ok, setOk] = useState(false);
  const hpcOn = !!status?.hpc.configured;
  const c = doe?.run_state_counts;
  const total = runs.length || doe?.run_count || 0;
  const collected = c?.COLLECTED ?? 0;
  const failed = (c?.SOLVE_FAILED ?? 0) + (c?.COLLECT_FAILED ?? 0);
  const missing = runs.filter((r) => r.state !== "COLLECTED");

  useEffect(() => {
    void reloadRuns();
  }, [imp.job?.id, imp.job?.version, reloadRuns]);

  return (
    <Card step="①-5" title="결과 회수">
      <p className="small">
        {hpcOn ? COLLECT_TEXT[status?.hpc.collect_mode ?? "in_place"] ?? `자동 회수(${status?.hpc.collect_mode})` : "PBS 연결 안 됨 — 해석한 결과 폴더를 직접 지정하세요"}
      </p>
      <DoePicker />
      <PathInput
        studyId={study.id}
        purpose="RESULT_FOLDER"
        label="결과 폴더 경로 (수동 지정)"
        placeholder="E:/shared/AI_WORK/cushion/00_inbox/pbs_results"
        value={path}
        onChange={setPath}
        canExecute={canExec && !!doe}
        extra={doe ? { doe_id: doe.id } : undefined}
        onInspected={(r) => setOk(!!r?.ok)}
        renderSummary={(r) => (
          <div className="summary-line">
            매칭 run <b>{String(r.summary.matched_runs ?? 0)}</b>개 · 파일 {String(r.summary.file_count ?? 0)}개
          </div>
        )}
      />
      <FeatureGate feature="train_import">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label="결과 가져오기"
            onRun={() => doe && void imp.run({ doe_id: doe.id, source_path: path.trim() })}
            job={imp.job}
            disabled={!enabled || !doe || !ok}
            disabledReason={enabled ? "결과 폴더를 입력하고 확인하세요" : undefined}
            error={imp.error}
          />
        )}
      </FeatureGate>
      {doe && (
        <div className="tiles" aria-label="회수 상태 요약">
          <div className="tile-stat ok">
            <span className="tile-num" data-testid="tile-collected">
              {collected}
              <span className="tile-den">/{total}</span>
            </span>
            <span className="tile-cap">회수</span>
          </div>
          <div className={`tile-stat ${failed ? "bad" : ""}`}>
            <span className="tile-num">{failed}</span>
            <span className="tile-cap">실패</span>
          </div>
          <div className="tile-stat">
            <span className="tile-num">{Math.max(0, total - collected - failed)}</span>
            <span className="tile-cap">미회수</span>
          </div>
        </div>
      )}
      {missing.length > 0 && (
        <details className="advanced">
          <summary>회수 안 된 run ({missing.length})</summary>
          <div className="mono small wrap-list">{missing.map((r) => r.run_key).join(", ")}</div>
        </details>
      )}
      <p className="note">회수한 결과는 ② 데이터 정리의 원천으로, 파라미터·샘플은 ④ "① 결과로 만들기"에 쓰입니다.</p>
    </Card>
  );
}
