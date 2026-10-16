import { useState } from "react";
import { api, errorMessage, type CurveJson, type Job, type JobStep, type PredictInputMode, type PredictJobParams, type PredictResult as PR, type ResponseRow } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { Card, CopyButton } from "../../components/ui";
import { Chart } from "../../components/Chart";
import { JsonTree } from "../../components/JsonTree";
import { useArtifactJson } from "../../hooks/useArtifact";
import { useCanExecute } from "../../hooks/useJobRunner";
import { ContourMedia } from "./ContourMedia";
import { fmtNum, fmtPct } from "../../lib/format";

/** 실행 체인 4단계: 형상 → 메싱 → 입력파일 → 예측 */
const CHAIN: { label: string; keys: string[] }[] = [
  { label: "형상", keys: ["PR_PREP", "TPL_RENDER", "GEOM_UPDATE"] },
  { label: "메싱", keys: ["MESH"] },
  { label: "입력파일", keys: ["RAD_ASSEMBLE"] },
  { label: "예측", keys: ["EDSPY_PREDICT", "CONTOUR_PREVIEW", "CURVE_PICK", "RESPONSE_EXTRACT", "RESPONSE_TABLE"] },
];

/** 준비된 입력(phase3.md §11.5): 형상·메싱 step은 SKIPPED라 숨기고 2단계로 묶는다 */
const CHAIN_PREPARED: { label: string; keys: string[] }[] = [
  { label: "입력파일", keys: ["PR_PREP", "RAD_ASSEMBLE"] },
  { label: "예측", keys: ["EDSPY_PREDICT", "CONTOUR_PREVIEW", "CURVE_PICK", "RESPONSE_EXTRACT", "RESPONSE_TABLE"] },
];

/** 작업의 입력 방식(params.input_mode 생략 = parametric) */
export function jobInputMode(job: Job | null): PredictInputMode | null {
  if (!job) return null;
  return (job.params as PredictJobParams).input_mode === "prepared" ? "prepared" : "parametric";
}

type ChainState = "pending" | "running" | "done" | "skipped" | "failed" | "canceled";
const CHAIN_LABEL: Record<ChainState, string> = {
  pending: "대기",
  running: "진행 중",
  done: "완료",
  skipped: "생략",
  failed: "실패",
  canceled: "취소",
};

function groupState(steps: JobStep[]): ChainState {
  if (!steps.length) return "pending";
  if (steps.some((s) => s.state === "FAILED")) return "failed";
  if (steps.some((s) => s.state === "RUNNING")) return "running";
  if (steps.some((s) => s.state === "CANCELED")) return "canceled";
  if (steps.every((s) => s.state === "SKIPPED")) return "skipped";
  if (steps.every((s) => s.state === "SUCCEEDED" || s.state === "SKIPPED")) return "done";
  if (steps.some((s) => s.state === "SUCCEEDED")) return "running";
  return "pending";
}

/** 실행 단계 표시. 작업이 있으면 작업의 입력 방식, 없으면 화면의 입력 방식(mode)을 따른다 */
export function PredictChain({ job, mode }: { job: Job | null; mode?: PredictInputMode }) {
  const prepared = (jobInputMode(job) ?? mode) === "prepared";
  const groups = prepared ? CHAIN_PREPARED : CHAIN;
  return (
    <ol className={`chain${prepared ? " prepared" : ""}`} aria-label="예측 실행 단계">
      {groups.map((g, i) => {
        const steps = job ? job.steps.filter((s) => g.keys.includes(s.step_key) && !(prepared && s.state === "SKIPPED")) : [];
        const st = job ? groupState(steps) : "pending";
        const failed = steps.find((s) => s.state === "FAILED");
        return (
          <li key={g.label} className={`chain-step ${st}`} title={failed ? `${failed.step_key}: ${failed.failure_code ?? ""} ${failed.failure_message ?? ""}` : undefined}>
            <span className="chain-no">{i + 1}</span>
            <span className="chain-label">{g.label}</span>
            <span className="chain-state">{CHAIN_LABEL[st]}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** 기존 결과 목록(미리보기 TCL 출력 JSON 트리) — 컨투어 미디어 아래 접힘 */
export function ResultListTree({ artifactId }: { artifactId: string | null | undefined }) {
  const preview = useArtifactJson<unknown>(artifactId);
  return (
    <details className="advanced result-list" data-testid="result-list">
      <summary>결과 목록</summary>
      <div className="run-tree">{preview ? <JsonTree data={preview} /> : <span className="muted small">{artifactId ? "불러오는 중…" : "결과 목록 없음"}</span>}</div>
    </details>
  );
}

export function CurveChart({ artifactId }: { artifactId: string }) {
  const curve = useArtifactJson<CurveJson>(artifactId);
  if (!curve) return null;
  return (
    <div className="curve">
      <div className="field-label">
        커브 <span className="muted small mono">{curve.file}</span>
      </div>
      <Chart
        height={240} aspect={0.38} maxHeight={560}
        ariaLabel="예측 커브"
        lines={curve.series.map((s, i) => ({ name: s.name, pts: s.x.map((x, j) => [x, s.y[j]] as [number, number]), className: `chart-line s${i % 4}` }))}
      />
      {curve.series.length > 1 && (
        <div className="legend small">
          {curve.series.map((s, i) => (
            <span key={s.name}>
              <span className={`lg line s${i % 4}`} /> {s.name}
            </span>
          ))}
        </div>
      )}
      {curve.note && <p className="muted small">{curve.note}</p>}
    </div>
  );
}

export function ResponseTable({ rows, verify, nearestRun }: { rows: ResponseRow[]; verify: Record<string, number> | null; nearestRun: string | null }) {
  if (!rows.length) return <p className="muted small">응답 정의 없음(파라미터 세트에 responses.json 없음)</p>;
  return (
    <table className="table compact" aria-label="응답값">
      <thead>
        <tr>
          <th>응답</th>
          <th>단위</th>
          <th className="num">예측</th>
          <th className="num">최근접 실측{nearestRun ? ` (${nearestRun})` : ""}</th>
          <th className="num">차이</th>
          {verify && <th className="num">PBS 검증</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name}>
            <td className="mono">{r.name}</td>
            <td className="small">{r.unit ?? ""}</td>
            <td className="num">{r.predicted == null ? <span className="muted small">추출 미구성</span> : fmtNum(r.predicted)}</td>
            <td className="num">{fmtNum(r.nearest_measured)}</td>
            <td className="num">{fmtPct(r.diff_pct)}</td>
            {verify && <td className="num">{fmtNum(verify[r.name])}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function baseName(p: string | null | undefined): string {
  return (p ?? "").split(/[\\/]/).filter(Boolean).pop() ?? "";
}

/** 결과 머리 한 줄: parametric은 적용값·범위, prepared는 starter 이름 */
function ResultHead({ job, result }: { job: Job; result: PR }) {
  const p = job.params as PredictJobParams;
  if (jobInputMode(job) === "prepared") {
    const path = p.input_path ?? result.input_path ?? "";
    return (
      <div className="result-head small" title={path}>
        준비된 입력 <span className="mono">{p.starter_name || baseName(path)}</span>
      </div>
    );
  }
  return (
    <div className="result-head small">
      입력{" "}
      {Object.entries(result.applied_values ?? result.values)
        .map(([k, v]) => `${k}=${v}`)
        .join(", ")}
      {" · "}
      {result.out_of_range?.length ? `학습 범위 밖${result.nearest ? ` · 최근접 ${result.nearest.run_key}` : ""}` : result.nearest ? `최근접 ${result.nearest.run_key} (거리 ${result.nearest.distance.toFixed(2)})` : ""}
    </div>
  );
}

/** "결과" 칸(B16·B17 입력파일 받기 포함). 두 입력 방식이 같이 쓴다 */
export function PredictResultCard({ job: pjob, verifyValues }: { job: Job | null; verifyValues: Record<string, number> | null }) {
  const { study, paramSets } = useStudy();
  const canCapture = useCanExecute();
  const result = pjob?.state === "SUCCEEDED" ? (pjob.result as unknown as PR | null) : null;
  // B16·B17: 입력파일은 RAD_ASSEMBLE 이후 준비(input_display_path가 채워짐) → input.zip
  const inputReady = !!pjob?.input_display_path;
  const captureViews = paramSets.find((p) => p.id === result?.param_set_id)?.display?.views ?? null;
  const [inputError, setInputError] = useState<string | null>(null);
  const downloadInput = async () => {
    if (!pjob) return;
    setInputError(null);
    try {
      const blob = await api.inputZip(pjob.id);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${study.folder_name}_${pjob.id.slice(0, 8)}_INPUT.zip`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setInputError(errorMessage(e));
    }
  };

  return (
    <Card
      span={9}
      title="결과"
      className="result"
      aside={
        pjob ? (
          <span className="run-action-row">
            {inputError && <span className="error-text small">{inputError}</span>}
            <button type="button" className="btn small" onClick={downloadInput} disabled={!inputReady} title={inputReady ? "INPUT 폴더의 .rad·.inc를 zip으로 받습니다" : "입력파일이 아직 준비되지 않았습니다"}>
              입력파일 받기
            </button>
          </span>
        ) : undefined
      }
    >
      {!result || !pjob ? (
        <p className="muted">{pjob && pjob.state !== "SUCCEEDED" ? "예측이 끝나면 결과가 여기에 표시됩니다." : "예측 결과가 없습니다."}</p>
      ) : (
        <>
          <ResultHead job={pjob} result={result} />
          {pjob.input_display_path && (
            <div className="codeline small" title="입력 폴더(탐색기에 붙여넣기)">
              <code>{pjob.input_display_path}</code>
              <CopyButton text={pjob.input_display_path} label="경로 복사" />
            </div>
          )}
          <div className="result-grid">
            <div className="result-contour">
              <ContourMedia jobId={pjob.id} canCapture={canCapture} captureViews={captureViews} />
              <ResultListTree artifactId={result.preview_json_artifact_id} />
            </div>
            <div className="result-side">
              {result.curve_artifact_id && <CurveChart artifactId={result.curve_artifact_id} />}
              <div>
                <div className="field-label">응답값</div>
                <ResponseTable rows={result.response_table ?? []} verify={verifyValues} nearestRun={result.nearest?.run_key ?? null} />
              </div>
            </div>
          </div>
        </>
      )}
    </Card>
  );
}
