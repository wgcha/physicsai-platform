import { useEffect, useState } from "react";
import { api, type CurveJson, type Job, type JobStep, type PredictResult as PR, type ResponseRow } from "../../api";
import { Chart } from "../../components/Chart";
import { fmtNum, fmtPct } from "../../lib/format";

/** 실행 체인 4단계: 형상 → 메싱 → 입력파일 → 예측 */
const CHAIN: { label: string; keys: string[] }[] = [
  { label: "형상", keys: ["PR_PREP", "TPL_RENDER", "GEOM_UPDATE"] },
  { label: "메싱", keys: ["MESH"] },
  { label: "입력파일", keys: ["RAD_ASSEMBLE"] },
  { label: "예측", keys: ["EDSPY_PREDICT", "CONTOUR_PREVIEW", "CURVE_PICK", "RESPONSE_EXTRACT", "RESPONSE_TABLE"] },
];

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

export function PredictChain({ job }: { job: Job | null }) {
  return (
    <ol className="chain" aria-label="예측 실행 단계">
      {CHAIN.map((g, i) => {
        const steps = job ? job.steps.filter((s) => g.keys.includes(s.step_key)) : [];
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

function useArtifactUrl(id: string | null | undefined) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!id) return;
    let alive = true;
    let obj: string | null = null;
    api
      .artifactBlob(id)
      .then((b) => {
        if (!alive) return;
        obj = URL.createObjectURL(b);
        setUrl(obj);
      })
      .catch(() => setUrl(null));
    return () => {
      alive = false;
      if (obj) URL.revokeObjectURL(obj);
    };
  }, [id]);
  return url;
}

function useArtifactJson<T>(id: string | null | undefined): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    setData(null);
    if (!id) return;
    let alive = true;
    api
      .artifactBlob(id)
      .then((b) => b.text())
      .then((t) => alive && setData(JSON.parse(t) as T))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [id]);
  return data;
}

function JsonTree({ data, depth = 0 }: { data: unknown; depth?: number }) {
  if (data === null || typeof data !== "object") return <span className="mono">{String(data)}</span>;
  const entries = Array.isArray(data) ? data.map((v, i) => [String(i), v] as const) : Object.entries(data as Record<string, unknown>);
  return (
    <ul className="tree">
      {entries.slice(0, 200).map(([k, v]) => (
        <li key={k}>
          {v !== null && typeof v === "object" ? (
            <details open={depth < 1}>
              <summary className="mono">{k}</summary>
              <JsonTree data={v} depth={depth + 1} />
            </details>
          ) : (
            <span>
              <span className="mono muted">{k}: </span>
              <span className="mono">{String(v)}</span>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

export function ContourPreview({ result }: { result: PR }) {
  const imgId = result.image_artifact_ids?.[0];
  const url = useArtifactUrl(imgId);
  const preview = useArtifactJson<unknown>(imgId ? null : result.preview_json_artifact_id);
  return (
    <div className="contour">
      <div className="field-label">컨투어</div>
      {imgId ? (
        url ? <img src={url} alt="예측 컨투어" className="contour-img" /> : <div className="empty small">불러오는 중…</div>
      ) : (
        <>
          <p className="muted small">컨투어 이미지 없음 — 미리보기 TCL 출력은 결과 목록입니다</p>
          {preview ? <JsonTree data={preview} /> : <div className="empty small">결과 목록 없음</div>}
        </>
      )}
    </div>
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
