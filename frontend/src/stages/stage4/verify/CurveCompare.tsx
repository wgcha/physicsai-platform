// FEM 검증 "커브" 탭(phase3 §21.3.11): 계열 드롭다운(여러 개일 때), 예측 = 실선 · FEM = 점선(범례 2개), 짝 없는 계열 회색 목록, SKIPPED 사유.
import { useEffect, useState } from "react";
import { errorMessage } from "../../../api";
import { femVerifyApi, type FemCompare, type FemCurves } from "../../../api/femVerify";
import { Chart } from "../../../components/Chart";

export function CurveCompare({ fid, curve }: { fid: string; curve: FemCompare["curve"] }) {
  const [name, setName] = useState<string | null>(null);
  const [data, setData] = useState<FemCurves | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ok = curve.status === "OK";
  useEffect(() => {
    if (!ok) return;
    let alive = true;
    setError(null);
    femVerifyApi
      .curves(fid, name ?? undefined)
      .then((r) => alive && setData(r))
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [fid, name, ok]);

  if (!ok) {
    return (
      <p className="muted small" data-testid="fv-curve-skipped">
        {curve.status === "FAILED" ? "커브 비교에 실패했습니다" : "커브 비교를 하지 않았습니다"}
        {curve.message ? ` — ${curve.message}` : ""}
      </p>
    );
  }
  const pts = (s: { x: number[]; y: number[] } | null) => (s ? s.x.map((x, i) => [x, s.y[i]] as [number, number]) : []);
  const lines = [
    ...(data?.pred ? [{ name: "예측", pts: pts(data.pred), className: "chart-line fv-pred" }] : []),
    ...(data?.fem ? [{ name: "FEM", pts: pts(data.fem), className: "chart-line fv-fem" }] : []),
  ];
  return (
    <div className="fv-section" data-testid="fv-curves">
      {error && <p className="error-text small" role="alert">{error}</p>}
      {(data?.names.length ?? 0) > 1 && (
        <label className="inline-field">
          계열
          <select value={data?.name ?? ""} onChange={(e) => setName(e.target.value)} aria-label="커브 계열">
            {data!.names.map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
      )}
      {lines.length > 0 && <Chart height={260} aspect={0.38} maxHeight={560} ariaLabel="예측·FEM 커브" lines={lines} />}
      <div className="legend small">
        <span>
          <span className="lg line fv-pred" /> 예측(실선)
        </span>
        <span>
          <span className="lg line fv-fem" /> FEM(점선)
        </span>
      </div>
      {data && !data.fem && <p className="muted small">이 계열은 FEM 쪽 짝이 없습니다.</p>}
      {data && !data.pred && <p className="muted small">이 계열은 예측 쪽 짝이 없습니다.</p>}
      {(curve.unmatched_pred.length > 0 || curve.unmatched_fem.length > 0) && (
        <div className="muted small" data-testid="fv-unmatched">
          {curve.unmatched_pred.length > 0 && <p>예측에만 있는 계열: {curve.unmatched_pred.join(", ")}</p>}
          {curve.unmatched_fem.length > 0 && <p>FEM에만 있는 계열: {curve.unmatched_fem.join(", ")}</p>}
        </div>
      )}
    </div>
  );
}
