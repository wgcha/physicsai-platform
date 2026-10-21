// ④ 일괄 예측 범위 표 — Native 템플릿(native-vars.md §7.3): 공용 NativeVarsTable(사용 체크·학습 범위·모핑 가능 범위·경고) + "변수 추가".
// 값(최소·최대)은 SamplingState.ranges가 들고 있고, 사용·추가·제외는 rows가 든다. 이 실행에만 적용(세트 정의는 ④ 템플릿 관리에서).
import type { ReactNode } from "react";
import type { NativeVars } from "../../../api";
import { typeLabel } from "../../../lib/geometry";
import { addable, type NativeRow } from "../../../lib/nativeVars";
import type { NativeExtraCol } from "../geometry/NativeVarsTable";
import { NativeVarsTable } from "../geometry/NativeVarsTable";
import type { Ranges } from "./samplingSource";

export interface NativeBatch {
  rows: NativeRow[];
  nv: NativeVars | null;
  canEdit: boolean;
  onBulkUse: (names: string[], use: boolean) => void;
  onRemove: (name: string) => void;
  onAdd: (name: string) => void;
}

export function NativeBatchVars({ native, ranges, locked, onRange, extra, note }: { native: NativeBatch; ranges: Ranges; locked: boolean; onRange: (name: string, i: 0 | 1, v: string) => void; extra?: NativeExtraCol[]; note?: ReactNode }) {
  const pool = native.nv ? addable(native.nv, native.rows) : [];
  // 범위 값은 일괄 상태의 문자열을 그대로 보여 준다(고정 열 없음 — 최소 = 최대는 기존 규칙대로 서버가 처리)
  const shown = native.rows.map((r) => ({ ...r, fixed: false, lo: ranges[r.name]?.[0] ?? r.lo, hi: ranges[r.name]?.[1] ?? r.hi }));
  return (
    <>
      <NativeVarsTable
        label="파라미터 범위" rows={shown} canEdit={native.canEdit} words={{ name: "파라미터", lo: "최소", hi: "최대" }} lockRange={locked}
        onPatch={(name, p) => {
          if (p.lo !== undefined) onRange(name, 0, p.lo);
          if (p.hi !== undefined) onRange(name, 1, p.hi);
          if (p.use !== undefined) native.onBulkUse([name], p.use);
        }}
        onBulkUse={native.onBulkUse} onRemove={native.onRemove} extra={extra} inputClass="num-input"
      />
      <div className="run-action-row small">
        {native.canEdit && pool.length > 0 && (
          <select value="" aria-label="변수 추가" onChange={(e) => e.target.value && native.onAdd(e.target.value)}>
            <option value="">변수 추가…</option>
            {pool.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name} · {typeLabel(p.type)} · {p.body}
              </option>
            ))}
          </select>
        )}
        <span className="muted" data-testid="vars-run-note">이 실행에만 적용(세트 정의는 ④ 템플릿 관리에서)</span>
      </div>
      {note}
    </>
  );
}
