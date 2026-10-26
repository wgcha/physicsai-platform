// Native 변수 표(native-vars.md §7): ④ 세트 상세·⑥ 내장 최적화·④ 일괄이 같이 쓰는 표. 사용 체크(다중 선택 후 일괄 — ①-2와 같은 엑셀식)·하한·상한·
// 학습 범위·모핑 가능 범위·경고(행별 아이콘 + 툴팁, 막지 않음). 값은 부모가 들고 있고(NativeRow[]) 이 표는 그리기·입력 전달만 한다.
import { Fragment, useMemo, type ReactNode } from "react";
import type { VarNote } from "../../../api/types";
import { BulkUseBar } from "../../../components/BulkUseBar";
import { fmtNum } from "../../../lib/format";
import { PITCH_TIP, isPitchType, typeLabel } from "../../../lib/geometry";
import { deltaText, mergedWarnings, notesByName, rowError, type NativeRow } from "../../../lib/nativeVars";
import { bulkTargets, useRowSelection, type RowSelection } from "../geomview/selection";

export interface NativeExtraCol {
  head: string;
  cell: (r: NativeRow) => ReactNode;
}

export interface NativeVarsTableProps {
  label: string;
  /** Altair 전체 tpl이면 Native 전용 열(종류·바디·모핑 가능 범위)을 숨긴다 */
  engine?: "native" | "altair";
  rows: NativeRow[];
  canEdit: boolean;
  /** 열 머리·입력 라벨 — 기본 변수·하한·상한(일괄 예측 = 파라미터·최소·최대) */
  words?: { name: string; lo: string; hi: string };
  onPatch: (name: string, patch: Partial<Pick<NativeRow, "use" | "lo" | "hi" | "fixed">>) => void;
  onBulkUse: (names: string[], use: boolean) => void;
  showBody?: boolean;
  /** 학습 범위 열(모델 기준 — ④ 세트 상세에는 없다) */
  showTrain?: boolean;
  showFixed?: boolean;
  /** 추가한 행의 [빼기] */
  onRemove?: (name: string) => void;
  /** 서버 경고(var_notes·warnings) */
  notes?: VarNote[];
  extra?: NativeExtraCol[];
  /** 행 선택을 3D 창과 공유할 때(③ 상세) */
  sel?: RowSelection;
  /** 값 입력 잠금(Sobol 이어서 추가 등) — 사용 체크는 그대로 */
  lockRange?: boolean;
  /** 종류 칸 툴팁(리브 피치: 열·빈 간격 안내, rib-gap.md §8) */
  typeTip?: (r: NativeRow) => string | undefined;
  /** 행 오른쪽 안내(회색) */
  rowNote?: (r: NativeRow) => ReactNode;
  testIdPrefix?: string;
  /** 표 안 입력 칸 너비 클래스 */
  inputClass?: string;
}

const range = (r: { min?: number | null; max?: number | null } | null | undefined) => (r ? `${r.min != null ? fmtNum(r.min) : "–"} ~ ${r.max != null ? fmtNum(r.max) : "–"}` : "–");

export function NativeVarsTable(p: NativeVarsTableProps) {
  const altair = p.engine === "altair";
  const { rows, canEdit, words = { name: "변수", lo: "하한", hi: "상한" }, showTrain = true } = p;
  const own = useRowSelection(useMemo(() => rows.map((r) => r.name), [rows]));
  const sel = p.sel ?? own;
  const byName = useMemo(() => notesByName(p.notes), [p.notes]);
  const lockRange = !!p.lockRange;
  const inputCls = p.inputClass ?? "num";
  return (
    <>
      <BulkUseBar count={sel.rows.length} disabled={!canEdit} onCheck={() => p.onBulkUse(sel.rows, true)} onUncheck={() => p.onBulkUse(sel.rows, false)} onClear={sel.clear} />
      <div className="table-wrap" ref={sel.tableRef}>
        <table className="table compact feature-table nv-table" aria-label={p.label}>
          <thead>
            <tr>
              <th>사용</th>
              <th>{words.name}</th>
              {!altair && <th>종류</th>}
              {p.showBody && !altair && <th>바디</th>}
              <th className="num">공칭</th>
              {showTrain && <th className="num">학습 범위</th>}
              {!altair && <th className="num">모핑 가능 범위</th>}
              <th className="num">{words.lo}</th>
              <th className="num">{words.hi}</th>
              {p.showFixed && <th>고정</th>}
              {p.extra?.map((c) => (
                <th key={c.head}>{c.head}</th>
              ))}
              <th>경고</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const rp = sel.rowProps(r.name);
              const warns = mergedWarnings(r, byName[r.name]);
              const err = rowError(r);
              const delta = r.use ? deltaText(r) : null;
              const off = !canEdit || !r.use;
              return (
                <tr key={r.name} {...rp} className={`${rp.className}${r.use ? "" : " unused"}`} data-testid={`${p.testIdPrefix ?? "var"}-${r.name}`}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`${r.name} 사용`}
                      checked={r.use}
                      disabled={!canEdit}
                      onChange={(e) => (sel.rows.includes(r.name) ? p.onBulkUse(bulkTargets(sel.rows, r.name), e.target.checked) : p.onPatch(r.name, { use: e.target.checked }))}
                    />
                  </td>
                  <td className="mono">
                    {r.name}
                    {r.integer && <span className="muted small" title="정수 형식 파라미터 — 하한·상한도 정수">{" "}정수</span>}
                    {r.origin === "added" && <span className="pill run" title="이 실행에만 추가한 변수(세트 정의에는 없음)">추가</span>}
                  </td>
                  {!altair && (
                    <td className="small" title={p.typeTip?.(r) ?? (isPitchType(r.type) ? PITCH_TIP : undefined)}>
                      {typeLabel(r.type)}
                      {isPitchType(r.type) && <span className="muted"> · mm 범위</span>}
                    </td>
                  )}
                  {p.showBody && !altair && <td className="mono small">{r.body}</td>}
                  <td className="num mono">{r.nominal != null ? fmtNum(r.nominal) : "–"}</td>
                  {showTrain && (
                    <td className="num mono small" data-testid={`train-${r.name}`}>
                      {r.train ? range(r.train) : <span className="muted">모름</span>}
                    </td>
                  )}
                  {!altair && <td className="num mono small">{range(r.feasible)}</td>}
                  <td className="num">
                    <input className={inputCls} inputMode={r.integer ? "numeric" : "decimal"} placeholder={r.rangeUnset ? "입력" : undefined} aria-label={`${r.name} ${words.lo}`} value={r.lo} disabled={off || lockRange} onChange={(e) => p.onPatch(r.name, { lo: e.target.value })} />
                  </td>
                  <td className="num">
                    {r.fixed && r.use ? (
                      <span className="muted">고정</span>
                    ) : (
                      <>
                        <input className={inputCls} inputMode={r.integer ? "numeric" : "decimal"} placeholder={r.rangeUnset ? "입력" : undefined} aria-label={`${r.name} ${words.hi}`} value={r.hi} disabled={off || lockRange} onChange={(e) => p.onPatch(r.name, { hi: e.target.value })} />
                        {delta && (
                          <span className="muted small nv-delta" title="공칭 대비 차이(mm)">
                            Δ {delta}
                          </span>
                        )}
                      </>
                    )}
                  </td>
                  {p.showFixed && (
                    <td>
                      <input type="checkbox" checked={r.fixed && r.use} disabled={off || lockRange} onChange={(e) => p.onPatch(r.name, { fixed: e.target.checked })} aria-label={`${r.name} 고정`} />
                    </td>
                  )}
                  {p.extra?.map((c) => (
                    <td key={c.head} className="small">
                      {c.cell(r)}
                    </td>
                  ))}
                  <td className="small nv-warn-cell">
                    {warns.map((w) => (
                      <span key={w.code} className={`nv-warn ${w.code === "VAR_OUT_OF_FEASIBLE" || w.code === "VAR_OUT_OF_BOUNDS" ? "bad" : "warn"}`} role="img" aria-label={w.message} title={w.message} data-code={w.code}>
                        ⚠
                      </span>
                    ))}
                    {err && <span className="error-text">{err}</span>}
                    {!err && r.rangeUnset && !r.use && r.lo.trim() === "" && <span className="muted">범위를 입력하세요</span>}
                    {p.onRemove && r.origin === "added" && (
                      <button type="button" className="btn small ghost" disabled={!canEdit} onClick={() => p.onRemove!(r.name)}>
                        빼기
                      </button>
                    )}
                    {p.rowNote && <Fragment>{p.rowNote(r)}</Fragment>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
