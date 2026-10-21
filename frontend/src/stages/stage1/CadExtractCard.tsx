import { useState } from "react";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Card, RunAction } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { FeatureGate } from "../../components/FeatureGate";
import { fmtTime } from "../../lib/format";
import { useTrain } from "./TrainContext";
import { EngineSelect, useGeometryStatus } from "../../components/EngineSelect";
import type { Engine } from "../../api";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ExtractFilterFields } from "../../components/ExtractFilterFields";
import { MSG, extractProblems, filterText, fromFilter, sameFilter, toFilter, validateForm, type FilterForm } from "../../lib/extractFilter";

// ---------------------------------------------------------------- ①-1
export function CadExtractCard() {
  const { study } = useStudy();
  const { setup, reloadSetup } = useTrain();
  const canExec = useCanExecute();
  const { job, run, error, errorDetail } = useJobRunner("TD_EXTRACT_PARAMS", () => void reloadSetup());
  const [path, setPath] = useState("");
  const [ok, setOk] = useState(false);
  const params = setup?.parameters ?? [];
  // geometry-engine.md §8 ①-1: 엔진 2단 선택, native는 STEP만
  const { engineDefault, nativeAvailable } = useGeometryStatus();
  const [engine, setEngine] = useState<Engine>(engineDefault);
  const native = engine === "native";
  // extract-filter.md §8 U1: 그 Study의 마지막 사용 조건(train_setups.extract_filter)이 있으면 미리 채우고, 없으면 다섯 그룹 모두 체크·빈칸. 고치면 그 값을 쓴다
  const [edit, setEdit] = useState<FilterForm | null>(null);
  const form = edit ?? fromFilter(setup?.extract_filter);
  const [staleDetail, setStaleDetail] = useState<unknown>(null);
  const serverProblems = errorDetail && errorDetail !== staleDetail ? extractProblems(errorDetail) : [];
  const [confirm, setConfirm] = useState(false);
  const formProblems = native ? validateForm(form) : [];
  const start = () => run(native ? { cad_path: path.trim(), engine, extract_filter: toFilter(form) } : { cad_path: path.trim() });
  // U2: 기존 표가 있는데 조건이 다르면(마지막 사용 조건 없음 포함) 확인 후 덮어쓴다(이전 표는 서버가 백업)
  const onRun = () => {
    if (native && params.length > 0 && !sameFilter(setup?.extract_filter, toFilter(form))) setConfirm(true);
    else void start();
  };

  return (
    <Card span={12} step="①-1" title="CAD 파라미터 추출">
      <div className="cad-row1">
        {nativeAvailable && <EngineSelect value={engine} onChange={setEngine} />}
        <PathInput
          studyId={study.id}
          purpose="CAD_FILE"
          label={native ? "CAD 파일 경로 (.step)" : "CAD 파일 경로 (.prt)"}
          placeholder={native ? "E:/shared/AI_WORK/cushion/00_inbox/cad/cushion_base.step" : "E:/shared/AI_WORK/cushion/00_inbox/cad/cushion_parametric_modeling.prt"}
          value={path}
          onChange={setPath}
          canExecute={canExec}
          extra={{ engine }}
          onInspected={(r) => setOk(!!r?.ok)}
          renderSummary={(r) => (
            <div className="summary-line">
              <span className="mono">{String(r.summary.file_name ?? "")}</span> · {Math.round(Number(r.summary.size ?? 0) / 1024).toLocaleString()} KB
              {r.summary.extension_ok === false && <span className="error-text small"> · 확장자 불가</span>}
            </div>
          )}
        />
      </div>
      {native && (
        <ExtractFilterFields
          wide
          value={form}
          onChange={(f) => {
            setEdit(f);
            setStaleDetail(errorDetail);
          }}
          serverProblems={serverProblems}
        />
      )}
      {job && (job.warnings ?? []).length > 0 && (
        <ul className="problems small muted" aria-label="추출 경고">
          {job.warnings.map((w, i) => (
            <li key={i}>{w.message ?? w.code}</li>
          ))}
        </ul>
      )}
      {confirm && (
        <ConfirmDialog
          title="파라미터 표를 바꿉니다"
          body={`기존 파라미터 표(${params.length}개, 적용 조건: ${filterText(setup?.extract_filter)})는 백업 후 새 결과로 바뀝니다.\n직접 고친 범위·사용 여부는 새 표에 옮겨지지 않습니다. 계속할까요?`}
          confirmLabel="바꾸기"
          onConfirm={() => {
            setConfirm(false);
            return start();
          }}
          onCancel={() => setConfirm(false)}
        />
      )}
      <div className="cad-row4">
        <div className="result-line small">
          {setup?.cad && (
            <>
              <span>
                추출 <b>{params.length}</b>개 (사용 가능 {params.filter((p) => p.valid).length})
              </span>
              <span className="mono ellipsis" title={setup.cad.display_path ?? undefined}>
                {setup.cad.file_name}
              </span>
              <span className="muted">{fmtTime(setup.updated_at)}</span>
            </>
          )}
        </div>
        <FeatureGate feature="train_extract">
          {(enabled) => (
            <RunAction
              canExecute={canExec}
              label="파라미터 추출"
              onRun={onRun}
              job={job}
              disabled={!enabled || !ok || formProblems.length > 0}
              disabledReason={enabled ? (!ok ? "CAD 파일 경로를 입력하고 확인하세요" : form.groups.length ? "추출 조건을 확인하세요" : MSG.noGroup) : undefined}
              error={error}
            />
          )}
        </FeatureGate>
      </div>
    </Card>
  );
}
