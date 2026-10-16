import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type InputMode, type Job, type PredictJobParams } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute } from "../../hooks/useJobRunner";
import { useFeature } from "../../components/FeatureGate";
import { Card } from "../../components/ui";
import { InputModeTabs, readInputMode, writeInputMode } from "./InputModeTabs";
import { ParamSetCard } from "./ParamSetCard";
import { PredictWorkspace } from "./PredictWorkspace";
import { PreparedPredictCard } from "./PreparedPredictCard";
import { PredictResultCard } from "./PredictResult";
import { TemplatePicker, useTemplateChoice } from "./TemplatePicker";
import { usePredictVerify } from "./predictRun";
import { BatchMode } from "./batch/BatchMode";

export { INPUT_MODE_KEY, TEMPLATE_OFF_TEXT } from "./InputModeTabs";

/** A 템플릿 값 입력: 템플릿 칸(형상 템플릿 드롭다운 포함) + 진행 + 결과, "템플릿 관리"는 펼칠 때만(템플릿이 없으면 항상) */
function TemplateMode() {
  const canExec = useCanExecute();
  const { list, ps, setPicked } = useTemplateChoice();
  const [manage, setManage] = useState(false);
  const aside = (
    <span className="run-action-row">
      <span className="muted small">관리자가 등록 · 사용자는 고르기만</span>
      {canExec && (
        <button type="button" className="btn small ghost" aria-expanded={manage} onClick={() => setManage((v) => !v)}>
          템플릿 관리
        </button>
      )}
    </span>
  );
  const picker = <TemplatePicker list={list} value={ps?.id ?? ""} onChange={setPicked} />;
  return (
    <>
      {ps ? (
        <PredictWorkspace key={ps.id} ps={ps} picker={picker} aside={aside} />
      ) : (
        <Card span={9} title="템플릿" aside={aside}>
          {picker}
          <p className="muted">등록된 템플릿이 없습니다{canExec ? " — 아래 템플릿 관리에서 등록하세요" : " — 관리자에게 등록을 요청하세요"}.</p>
        </Card>
      )}
      {(manage || (!ps && canExec)) && <ParamSetCard ps={ps} />}
    </>
  );
}

/** "단일 예측으로 열기"(일괄 예측 결과 → ?job=<하위 PREDICT id>): 그 작업의 결과 칸(컨투어 결과 목록·커브·응답·입력파일) */
function OpenedJob({ id }: { id: string }) {
  const { study } = useStudy();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.job(id).then(setJob).catch((e) => setError(String(e?.message ?? e)));
  }, [id]);
  const pbs = usePredictVerify(job, job?.state === "SUCCEEDED");
  const br = job?.batch ?? null;
  const p = job?.params as PredictJobParams | undefined;
  const base = `/p/${study.project_id}/s/${study.id}/stage/4`;
  return (
    <>
      <Card span={9} title={br ? `일괄 예측 ${br.label} · DOE #${br.doe_no ?? "?"}` : "예측 작업"} aside={br ? <Link to={`${base}/batch/${br.id}`}>← 일괄 예측 결과</Link> : <Link to={base}>닫기</Link>}>
        {error ? <p className="error-text small">{error}</p> : <p className="muted small mono ellipsis">{p?.input_path ?? id}</p>}
        <div className="run-action-row">
          {pbs.button}
          {pbs.notes}
        </div>
      </Card>
      <PredictResultCard job={job} verifyValues={pbs.verifyValues} />
    </>
  );
}

/** ④ 예측(§16.5, phase3.md §14.8) — 입력 방식: 템플릿 값 입력(기본) / 일괄 예측(DOE) / 준비된 입력 파일 */
export function Stage4() {
  const parametric = useFeature("predict_parametric");
  const meshOnly = useFeature("predict_mesh_only");
  const templateEnabled = parametric.enabled || meshOnly.enabled;
  const [stored, setStored] = useState<InputMode>(readInputMode);
  const [search, setSearch] = useSearchParams();
  const openJob = search.get("job");
  const mode: InputMode = templateEnabled ? stored : "prepared";
  const choose = (m: InputMode) => {
    setStored(m);
    writeInputMode(m);
    if (openJob) setSearch({}, { replace: true });
  };
  return (
    <>
      <InputModeTabs mode={mode} templateEnabled={templateEnabled} onChange={choose} />
      {openJob ? <OpenedJob key={openJob} id={openJob} /> : mode === "template" ? <TemplateMode /> : mode === "batch" ? <BatchMode /> : <PreparedPredictCard />}
    </>
  );
}
