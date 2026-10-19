import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { type InputMode } from "../../api";
import { predictRunsApi } from "../../api/predictRuns";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute } from "../../hooks/useJobRunner";
import { useFeature } from "../../components/FeatureGate";
import { Card } from "../../components/ui";
import { InputModeTabs, readInputMode, writeInputMode } from "./InputModeTabs";
import { ParamSetCard } from "./ParamSetCard";
import { PredictWorkspace } from "./PredictWorkspace";
import { PreparedPredictCard } from "./PreparedPredictCard";
import { TemplatePicker, useTemplateChoice } from "./TemplatePicker";
import { BatchMode } from "./batch/BatchMode";
import { PredictRunList } from "./history/PredictRunList";
import { PredictRunView } from "./history/PredictRunView";
import { SingleTabs, readSingleTab, writeSingleTab, type SingleTab } from "./history/SingleTabs";

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

/** ④ 예측(§16.5, phase3.md §14.8·§21.2) — 입력 방식: 템플릿 값 입력(기본) / 일괄 예측(DOE) / 준비된 입력 파일. 템플릿·준비된 입력은 하위 탭 "새 예측 | 실행 목록" */
export function Stage4() {
  const { study } = useStudy();
  const parametric = useFeature("predict_parametric");
  const meshOnly = useFeature("predict_mesh_only");
  const templateEnabled = parametric.enabled || meshOnly.enabled;
  const [stored, setStored] = useState<InputMode>(readInputMode);
  const [search, setSearch] = useSearchParams();
  const openJob = search.get("job");
  const mode: InputMode = templateEnabled ? stored : "prepared";
  const [tab, setTab] = useState<SingleTab>(() => readSingleTab() ?? "new");
  const chosen = useRef(false);
  // 기본 탭: 진행 중(QUEUED·RUNNING) 단일 예측이 있으면 실행 목록(사용자가 이미 고르지 않았을 때만)
  useEffect(() => {
    let alive = true;
    predictRunsApi
      .list(study.id, { mode: "all", state: "QUEUED,RUNNING", limit: 1 })
      .then((r) => alive && !chosen.current && r.items.length && setTab("list"))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [study.id]);
  const chooseTab = (t: SingleTab) => {
    chosen.current = true;
    setTab(t);
    writeSingleTab(t);
  };
  const choose = (m: InputMode) => {
    setStored(m);
    writeInputMode(m);
    if (openJob) setSearch({}, { replace: true });
  };
  const backToList = () => {
    chooseTab("list");
    setSearch({});
  };
  const single = mode === "template" || mode === "prepared";
  return (
    <>
      <InputModeTabs mode={mode} templateEnabled={templateEnabled} onChange={choose} />
      {openJob ? (
        <PredictRunView key={openJob} id={openJob} onBackToList={backToList} />
      ) : (
        <>
          {single && <SingleTabs tab={tab} onChange={chooseTab} />}
          {mode === "batch" ? <BatchMode /> : tab === "list" ? <PredictRunList key={mode} initialMode={mode === "prepared" ? "prepared" : "template"} onNew={() => chooseTab("new")} /> : mode === "template" ? <TemplateMode /> : <PreparedPredictCard />}
        </>
      )}
    </>
  );
}
