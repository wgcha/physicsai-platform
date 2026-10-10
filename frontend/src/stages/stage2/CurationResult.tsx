import { Link } from "react-router-dom";
import { type Curation } from "../../api";
import { CodeLine } from "../../components/ui";
import { CurationFileList } from "./CurationFileList";

export function CurationResult({ cur, datasetLink }: { cur: Curation; datasetLink?: string }) {
  if (cur.status === "BUILDING") return <p className="muted small">큐레이션 진행 중…</p>;
  if (cur.status === "FAILED") return <p className="error-text small">큐레이션 실패</p>;
  return (
    <div className="curation-result" data-testid="curation-result">
      <div className="small">
        성공 <b>{cur.ok_count}</b>/{cur.target_count}
        {(cur.failed_count ?? 0) > 0 && <span className="error-text"> · 실패 {(cur.failed_count ?? 0)}</span>}
        {cur.missing_runs.length > 0 && <span className="muted"> · 누락 run {cur.missing_runs.length}</span>}
      </div>
      <CodeLine text={cur.output_display_path} />
      {((cur.failed_count ?? 0) > 0 || cur.missing_runs.length > 0) && (
        <details className="advanced">
          <summary>실패 파일·누락 run</summary>
          <div className="advanced-body grid-gap">
            {(cur.failed_count ?? 0) > 0 && <CurationFileList curationId={cur.id} onlyFailed />}
            {cur.missing_runs.length > 0 && (
              <div className="small">
                <div className="field-label">누락 run (출력 없음)</div>
                <div className="mono wrap-list">{cur.missing_runs.join(", ")}</div>
              </div>
            )}
          </div>
        </details>
      )}
      {cur.kind === "H3D" && (
        <p className="small">
          {cur.used_by_dataset_ids.length ? "③-1 입력으로 사용됨" : "③-1 데이터셋 생성의 기본 입력으로 연결됩니다"}
          {datasetLink && (
            <>
              {" · "}
              <Link to={datasetLink}>③-1로 이동</Link>
            </>
          )}
        </p>
      )}
    </div>
  );
}
