// S17 파레토 표(phase3.md §22.12): 행 = 검증된 파레토 해(+ 토글 켜면 예측 전선 행 — 회색 기울임 "예측(미검증)").
// 열: 선택 · 출처 · 반복·배치·DOE # · 변수 · 목적 · 제약 · 관찰 · 가중 점수 · 순위. 정렬 = 점수 오름차순, 추천 행 강조.
// 동작: 단일 예측으로 열기(검증 해 1개) · 선택 해 예측 검증(1~10개, 컨투어 캡처 선택, POST verify) · FEM 검증(검증 해 1개, S16) · CSV 받기.
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorMessage } from "../../../api";
import { surrogateApi, type SoConstraintDef, type SurrogateOpt, type SurrogateOptVerifyResult } from "../../../api/surrogateOpt";
import { useApp } from "../../../app/AppContext";
import { Card } from "../../../components/ui";
import { useCanExecute } from "../../../hooks/useJobRunner";
import { fmtNum } from "../../../lib/format";
import { FEM_BUTTON_LABEL } from "../../stage4/verify/verifyRules";
import { useFemVerifyButton } from "../../stage4/verify/useFemVerifyButton";
import type { ParetoModel, ParetoPt } from "./paretoView";
import { PRED_NOTE, SCORE_TIP, VERIFY_FIRST_TEXT } from "./paretoView";
import { fmtVar, isSurrogateOnly, levelsOf } from "./soRules";

export const KIND_LABEL: Record<string, string> = { EXPLORE: "탐색", REUSE: "재사용", VERIFY: "검증", EXTRA: "추가" };
export const EXTRA_DONE_NOTE = "검증이 끝나면 이 표에 반영됩니다";
const ACTIVE_BATCH = ["GENERATING", "PREDICTING"];

function constraintBound(c: SoConstraintDef): string {
  return c.op === "range" ? `${fmtNum(c.lo)} ~ ${fmtNum(c.hi)}` : `${c.op === "<=" ? "≤" : "≥"} ${fmtNum(c.value)}`;
}

export function ParetoTable({ o, model, sel, onToggle, showPred, base, onChanged, downloadCsv }: {
  o: SurrogateOpt;
  model: ParetoModel;
  sel: Set<string>;
  onToggle: (key: string) => void;
  showPred: boolean;
  /** …/p/:pid/s/:sid */
  base: string;
  onChanged: () => void;
  downloadCsv: () => void;
}) {
  const { status } = useApp();
  const navigate = useNavigate();
  const canExec = useCanExecute();
  const [capture, setCapture] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<SurrogateOptVerifyResult | null>(null);
  const maxExtra = (status as { surrogate_opt?: { max_extra_points?: number } } | null)?.surrogate_opt?.max_extra_points ?? 10;
  const names = (o.settings as { names?: string[] }).names ?? [];
  const cons = o.constraints_def ?? [];
  const obs = o.observe ?? [];

  const rows = useMemo(() => {
    const f = [...model.front].sort((a, b) => (a.score ?? Infinity) - (b.score ?? Infinity));
    const p = showPred ? [...model.predicted].sort((a, b) => (a.score ?? Infinity) - (b.score ?? Infinity)) : [];
    return [...f, ...p];
  }, [model, showPred]);
  const chosen = rows.filter((r) => sel.has(r.key));
  const verifiedOne: ParetoPt | null = chosen.length === 1 && chosen[0].kind === "front" && chosen[0].job_id ? chosen[0] : null;
  const hasPred = chosen.some((r) => r.kind === "pred");
  const fem = useFemVerifyButton(verifiedOne ? { kind: "opt_design", opt_id: o.id, pick: "run", iter_no: verifiedOne.iter_no ?? 0, doe_no: verifiedOne.doe_no ?? 0 } : null, !!verifiedOne);

  const extraActive = (o.iterations ?? []).some((it) => it.kind === "EXTRA" && it.batch && ACTIVE_BATCH.includes(it.batch.status));
  const verifyReason = !canExec ? null : o.status !== "DONE" ? "최적화가 끝난 뒤 추가 검증할 수 있습니다" : extraActive || busy ? "추가 검증이 진행 중입니다" : !o.can_verify_more ? "지금은 추가 검증을 시작할 수 없습니다" :
    !chosen.length ? "검증할 해를 고르세요" : chosen.length > maxExtra ? `한 번에 ${maxExtra}개까지` : null;
  const verify = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await surrogateApi.verify(o.id, { points: chosen.map((p) => ({ values: p.values })), capture });
      setLast(r);
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const femReason = !verifiedOne ? (hasPred ? VERIFY_FIRST_TEXT : "검증된 해 1개를 고르세요") : undefined;
  const stage4 = `${base}/stage/4`;

  return (
    <Card span={9} title="파레토 표" className="so-pareto-table" aside={<span className="muted small" title={SCORE_TIP}>정렬: 가중 점수 낮은 순 · 계산식 ⓘ</span>}>
      {!rows.length ? (
        <p className="muted small" data-testid="pareto-empty">아직 검증된 파레토 해가 없습니다.</p>
      ) : (
        <div className="table-wrap">
          <table className="table compact" aria-label="파레토 표">
            <thead>
              <tr>
                <th />
                <th>출처</th>
                <th>반복 · 배치 · DOE #</th>
                {names.map((n) => <th key={n} className="num mono">{n}</th>)}
                {model.defs.map((d) => <th key={d.metric} className="num" title={d.label}>{d.label}{d.unit ? ` [${d.unit}]` : ""}</th>)}
                {cons.map((c) => <th key={c.metric} className="num" title={c.label}>{c.label} <span className="muted">({constraintBound(c)})</span></th>)}
                {obs.map((c) => <th key={c.metric} className="num" title={c.label}>{c.label} <span className="muted">관찰</span></th>)}
                <th className="num" title={SCORE_TIP}>가중 점수</th>
                <th className="num">순위</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const pred = r.kind === "pred";
                const rec = !pred && r.key === model.rec.key;
                return (
                  <tr key={r.key} data-testid={`prow-${r.key}`} className={`${sel.has(r.key) ? "selected" : ""}${rec ? " recommended" : ""}${pred ? " so-pred-row" : ""}`}>
                    <td><input type="checkbox" checked={sel.has(r.key)} onChange={() => onToggle(r.key)} aria-label={`${pred ? "예측 점" : `${r.batch_label} DOE #${r.doe_no}`} 선택`} /></td>
                    <td className="small">{pred ? PRED_NOTE : KIND_LABEL[r.run_kind ?? ""] ?? "검증"}{rec && <span className="pill ok"> 추천</span>}</td>
                    <td className="small">{pred ? <span className="muted">—</span> : <>{r.iter_no} · {r.batch_label} · #{r.doe_no}</>}</td>
                    {names.map((n) => <td key={n} className="num mono">{fmtVar(n, r.values[n], levelsOf(o))}</td>)}
                    {r.f.map((v, i) => (
                      <td key={i} className="num mono">{fmtNum(v)}{pred && r.std?.[i] != null ? <span className="muted small"> ±{fmtNum(r.std[i])}</span> : null}</td>
                    ))}
                    {cons.map((c) => <td key={c.metric} className="num mono">{pred ? <span className="muted">{r.pof != null ? `확률 ${fmtNum(r.pof, 2)}` : "—"}</span> : fmtNum(r.constraints[c.metric])}</td>)}
                    {obs.map((c) => <td key={c.metric} className="num mono">{pred ? <span className="muted">—</span> : fmtNum(r.observed[c.metric])}</td>)}
                    <td className="num mono" data-testid={`score-${r.key}`}>{r.score != null ? r.score.toFixed(3) : "—"}</td>
                    <td className="num" data-testid={`rank-${r.key}`}>{pred ? "—" : model.rank[r.key]}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="run-action-row so-actions">
        <button type="button" className="btn small" disabled={!verifiedOne} title={!verifiedOne ? (femReason ?? undefined) : undefined}
          onClick={() => verifiedOne?.job_id && navigate(`${stage4}?job=${verifiedOne.job_id}`)}>
          단일 예측으로 열기
        </button>
        {canExec && (
          <>
            <button type="button" className={`btn primary${isSurrogateOnly(o) ? "" : " small"}`} data-testid="pareto-verify" disabled={!!verifyReason || busy} title={verifyReason ?? undefined} onClick={() => void verify()}>
              선택 해 예측 검증{chosen.length ? ` (${chosen.length})` : ""}
            </button>
            <label className="check small">
              <input type="checkbox" checked={capture} onChange={(e) => setCapture(e.target.checked)} /> 컨투어 캡처 포함
            </label>
          </>
        )}
        {verifiedOne ? fem.button : canExec ? <button type="button" className="btn" disabled title={femReason}>{FEM_BUTTON_LABEL}</button> : null}
        <button type="button" className="btn small" onClick={downloadCsv}>CSV 받기</button>
      </div>
      {verifiedOne && fem.notes}
      {last && (
        <p className="small" data-testid="extra-note">
          추가 검증 <Link to={`${base}/stage/4/batch/${last.batch_id}`} data-testid="extra-link">{last.batch_label}</Link> 시작 — {EXTRA_DONE_NOTE}
        </p>
      )}
      {!last && extraActive && <p className="muted small" data-testid="extra-note">추가 검증이 진행 중입니다 — {EXTRA_DONE_NOTE}</p>}
      {error && <p className="error-text small" role="alert">{error}</p>}
      {isSurrogateOnly(o) && <p className="small" data-testid="none-verify-hint">대리모델만(검증 없음) 결과입니다 — 예측 점을 골라 '선택 해 예측 검증'으로 확인하세요.</p>}
      <p className="muted small">가중합은 전선의 오목한 부분의 해를 고를 수 없어, 표에서 직접 고르는 것이 기본입니다. 예측(미검증) 점은 예측 검증을 거친 뒤에만 FEM 검증 대상이 됩니다.</p>
    </Card>
  );
}
