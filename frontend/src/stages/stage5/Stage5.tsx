import { useCallback, useEffect, useState } from "react";
import { api, type Optimization, type OptResponse, type ResponseCandidates } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { FeatureOffNote, useFeature } from "../../components/FeatureGate";
import { Card } from "../../components/ui";
import { ResponseAddRow, ResponseTable } from "./ResponseTable";
import { OptInputCard } from "./OptInputCard";
import { OptResult } from "./OptResult";
import { OptRunCard } from "./OptRunCard";
import { OptModeTabs, useOriginalVisible } from "./OptModeTabs";
import { SurrogateMode } from "./surrogate/SurrogateMode";
import { readMode, writeMode, type OptMode } from "./surrogate/soRules";
import { type RunSettings } from "./rules";

/** 이슈 #4(phase3.md §18.8): 쿠션 단독 템플릿은 원본 최적화 불가(서버 409 TEMPLATE_ASSEMBLY_REQUIRED와 같은 문구) */
export const ASSEMBLY_REQUIRED_TEXT =
  "이 템플릿은 조립 폴더가 없는 쿠션 단독(메시 단독) 템플릿이라 원본 최적화를 실행할 수 없습니다 — '플랫폼 내장(쿠션만 가능)' 모드를 쓰세요";

/** ⑤ 최적화(phase2.md §14.5 + phase3.md §18.10 모드 선택 + opt-native §4.4 레거시 숨김) */
export function Stage5() {
  const builtin = useFeature("optimize_builtin");
  const showOriginal = useOriginalVisible();
  const [picked, setPicked] = useState<OptMode>(() => readMode());
  // 원본 탭이 숨겨졌는데 저장 값이 original이면 builtin으로 바꾼다(내장이 꺼져도 원본으로 떨어지지 않는다)
  const mode: OptMode = picked === "original" && !showOriginal ? "builtin" : picked;
  useEffect(() => {
    if (picked === "original" && !showOriginal) writeMode("builtin");
  }, [picked, showOriginal]);
  const choose = (m: OptMode) => {
    setPicked(m);
    writeMode(m);
  };
  return (
    <>
      <OptModeTabs mode={mode} onChange={choose} />
      {mode === "original" ? <OriginalOptimize onUseBuiltin={() => choose("builtin")} /> : builtin.enabled ? <SurrogateMode /> : (
        <Card span={9} title="플랫폼 내장 최적화">
          <p className="muted small">플랫폼 내장 최적화를 쓸 수 없습니다.</p>
          <FeatureOffNote feature="optimize_builtin" f={builtin} />
        </Card>
      )}
    </>
  );
}

function OriginalOptimize({ onUseBuiltin }: { onUseBuiltin: () => void }) {
  const { study, currentParamSet } = useStudy();
  const canExec = useCanExecute();
  const [modelId, setModelId] = useState("");
  const [responses, setResponses] = useState<OptResponse[]>([]);
  const [cands, setCands] = useState<ResponseCandidates | null>(null);
  const [opts, setOpts] = useState<Optimization[]>([]);
  const [s, setS] = useState<RunSettings>({
    approach: "OPT", method: "ARSM", maxDesigns: "25", runNominal: true, studyFolder: "HST_PHYSICSAI_OPTIMIZATION", abs: "0.001", rel: "1.0", dv: "0.001", onFailed: "IGNORE",
  });
  const loadOpts = useCallback(() => api.optimizations(study.id).then(setOpts).catch(() => undefined), [study.id]);
  const runner = useJobRunner("OPTIMIZE", () => void loadOpts());

  useEffect(() => {
    api.responseCandidates(study.id, modelId || null).then(setCands).catch(() => setCands(null));
  }, [study.id, modelId]);
  useEffect(() => {
    void loadOpts();
  }, [loadOpts, runner.job?.id, runner.job?.version]);

  const latest = [...opts].sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;
  // 서버 needs_assembly_block과 같은 판정: mesh_only 또는 조립 폴더·starter 없음
  const meshOnly = !!currentParamSet && (currentParamSet.input_kind === "mesh_only" || !currentParamSet.assem_rel || !currentParamSet.starter_name);

  return (
    <>
      <OptInputCard modelId={modelId} setModelId={setModelId} />
      <Card span={6} step="⑥-2" title="응답">
        <ResponseTable rows={responses} onChange={setResponses} readOnly={!canExec} />
        {canExec && <ResponseAddRow candidates={cands} rows={responses} onAdd={(r) => setResponses([...responses, r])} />}
        <p className="muted small">Goal이 CONSTRAINT일 때만 Bound·Value를 씁니다. 단위계 mm-ton-s.</p>
      </Card>
      {meshOnly ? (
        <Card span={3} step="⑥-3" title="실행" foot={
          <div className="run-action-row">
            <button type="button" className="btn primary" disabled title={ASSEMBLY_REQUIRED_TEXT}>최적화 실행</button>
            <button type="button" className="btn small" onClick={onUseBuiltin}>플랫폼 내장으로</button>
          </div>
        }>
          <div className="warn-box" role="alert" data-testid="assembly-required">{ASSEMBLY_REQUIRED_TEXT}</div>
        </Card>
      ) : (
        <OptRunCard s={s} setS={setS} responses={responses} modelId={modelId} runner={runner} />
      )}
      <Card span={6} step="⑥-4" title="결과">
        <OptResult opt={latest} job={runner.job} />
      </Card>
    </>
  );
}
