// ④ 준비된 입력 예측(phase3.md §11.5): 경로 확인 → 모델(기본 Final) → 예측 실행. 결과 칸은 parametric과 같은 컴포넌트.
import { useState } from "react";
import {
  api,
  errorMessage,
  type PathInspectResult,
  type PredictInputInspect,
  type PredictInputProblem,
  type PredictParamsPrepared,
  type PredictResult as PR,
} from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Card, RunAction } from "../../components/ui";
import { FeatureGate } from "../../components/FeatureGate";
import { PredictChain, PredictResultCard } from "./PredictResult";
import { ModelLine, useModelChoice, usePredictVerify } from "./predictRun";

export const DIRECT_FILES_NOTE = "직계 파일만 복사합니다 — 폴더(또는 .rad 파일의 폴더)의 .rad·.inc만, 하위 폴더·EPS_mesh 제외. .hm은 그 파일만.";

/** inspect 응답에서 PREDICT_INPUT 요약을 꺼낸다(요약 키는 summary 안, problems는 최상위 — phase3 D3-30) */
export function predictInputInfo(r: PathInspectResult): PredictInputInspect & { ok: boolean } {
  const sum = (r.summary ?? {}) as Partial<PredictInputInspect>;
  const pick = <K extends keyof PredictInputInspect>(k: K): PredictInputInspect[K] | undefined => sum[k] as PredictInputInspect[K] | undefined;
  const seen = new Set<string>();
  const problems: PredictInputProblem[] = [];
  for (const p of r.problems ?? []) {
    const key = `${p.code}|${p.message ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    problems.push({ code: p.code, message: p.message ?? p.code });
  }
  const starter = pick("starter") ?? [];
  const starterOk = pick("starter_ok") ?? starter.length === 1;
  return {
    kind: pick("kind") ?? "file",
    starter,
    starter_ok: starterOk,
    rad: pick("rad") ?? [],
    inc_count: pick("inc_count") ?? 0,
    file_count: pick("file_count") ?? 0,
    total_bytes: pick("total_bytes") ?? 0,
    problems,
    ok: r.ok && starterOk && problems.length === 0,
  };
}

/** 요약 한 줄 "starter · rad N · inc M" */
export function inputSummaryLine(i: PredictInputInspect): string {
  const hm = i.starter.some((s) => /\.hm$/i.test(s));
  const radN = Math.max(i.rad.length, hm ? 0 : i.file_count - i.inc_count);
  return `${i.starter.length ? i.starter.join(", ") : "starter 없음"} · rad ${radN} · inc ${i.inc_count}`;
}

function ProblemNotes({ problems, testId }: { problems: PredictInputProblem[]; testId: string }) {
  if (!problems.length) return null;
  return (
    <ul className="plain-notes" data-testid={testId}>
      {problems.map((p, i) => (
        <li key={i} className="muted small" data-code={p.code}>
          {p.message}
        </li>
      ))}
    </ul>
  );
}

export function PreparedPredictCard() {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const choice = useModelChoice();
  const predict = useJobRunner("PREDICT");
  const [path, setPath] = useState("");
  const [info, setInfo] = useState<(PredictInputInspect & { ok: boolean }) | null>(null);
  const [inspectError, setInspectError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const inspect = async () => {
    setBusy(true);
    setInspectError(null);
    try {
      setInfo(predictInputInfo(await api.inspectPath(study.id, "PREDICT_INPUT", path.trim())));
    } catch (e) {
      setInfo(null);
      setInspectError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const runPredict = () => {
    const params: PredictParamsPrepared = {
      input_mode: "prepared",
      input_path: path.trim(),
      model_id: choice.modelId || null,
      param_set_id: null,
    };
    void predict.run({ ...params });
  };

  const pjob = predict.job;
  const result = pjob?.state === "SUCCEEDED" ? (pjob.result as unknown as PR | null) : null;
  const pbs = usePredictVerify(pjob, !!result);
  const runProblems = predict.errorDetail?.code === "PREDICT_INPUT_INVALID" ? ((predict.errorDetail.problems as PredictInputProblem[] | undefined) ?? []) : [];

  return (
    <>
      <Card span={9} title="준비된 입력 파일" className="inputs prepared">
        <div className="prepared-input">
          <div className="pathinput">
            <span className="field-label">입력 파일(.rad·.hm) 또는 폴더 경로</span>
            <div className="pathinput-row">
              <input
                type="text"
                className="mono"
                value={path}
                placeholder="E:/shared/AI_WORK/cushion/00_inbox/case_A/Face_Drop_0000.rad"
                aria-label="준비된 입력 경로"
                spellCheck={false}
                disabled={!canExec}
                onChange={(e) => {
                  setPath(e.target.value);
                  setInfo(null);
                }}
              />
              <button type="button" className="btn" onClick={inspect} disabled={!canExec || busy || !path.trim()}>
                {busy ? "확인 중…" : "확인"}
              </button>
            </div>
            {inspectError && <div className="error-text small" role="alert">{inspectError}</div>}
            {info && (
              <p className="small prepared-summary" data-testid="prepared-summary">
                {inputSummaryLine(info)}
              </p>
            )}
            {info && <ProblemNotes problems={info.problems} testId="prepared-problems" />}
            <p className="muted small">{DIRECT_FILES_NOTE}</p>
          </div>
        </div>
        <div className="run-block">
          <ModelLine choice={choice} />
          <FeatureGate feature="predict">
            {(enabled) => (
              <RunAction
                canExecute={canExec}
                label="예측 실행"
                onRun={runPredict}
                job={pjob}
                disabled={!enabled || !choice.chosenModel || !info?.ok}
                disabledReason={!enabled ? undefined : !choice.chosenModel ? "Final 모델이 필요합니다" : !info ? "경로를 확인하세요" : !info.ok ? "준비된 입력을 쓸 수 없습니다" : undefined}
                error={predict.error}
                extra={pbs.button}
              />
            )}
          </FeatureGate>
          <ProblemNotes problems={runProblems} testId="prepared-run-problems" />
          {pbs.notes}
          <PredictChain job={pjob} mode="prepared" />
        </div>
      </Card>
      <PredictResultCard job={pjob} verifyValues={pbs.verifyValues} />
    </>
  );
}
