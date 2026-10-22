// ⑥ ④ 변수 범위 카드 — Native 템플릿(native-vars.md §7.2): 세트 정의로 초기화, 그 자리에서 변수 추가(풀에서 선택)·제외(공칭 유지)·범위 변경.
// '고정'(하한 = 상한, 변수 목록에 남음)과 '제외'(공칭 유지, 결과 표에 없음)는 별개 열. 범위 밖은 막지 않고 경고만(NV-7). 이 실행에만 적용한다.
import type { NativeVars, VarNote } from "../../../api";
import { Card } from "../../../components/ui";
import { typeLabel } from "../../../lib/geometry";
import { addable, generalNotes, type NativeRow } from "../../../lib/nativeVars";
import { NativeVarsTable } from "../../stage4/geometry/NativeVarsTable";

interface Props {
  /** Altair 전체 tpl이면 Native 전용 열을 숨기고 변수 추가 후보에 종류·바디를 쓰지 않는다 */
  engine?: "native" | "altair";
  rows: NativeRow[];
  nv: NativeVars | null;
  canEdit: boolean;
  /** 미리보기 var_notes(서버 경고·안내) */
  notes?: VarNote[];
  onPatch: (name: string, p: Partial<Pick<NativeRow, "use" | "lo" | "hi" | "fixed">>) => void;
  onBulkUse: (names: string[], use: boolean) => void;
  onRemove: (name: string) => void;
  onAdd: (name: string) => void;
}

export function NativeVarsCard({ engine = "native", rows, nv, canEdit, notes, onPatch, onBulkUse, onRemove, onAdd }: Props) {
  const pool = nv ? addable(nv, rows) : [];
  const info = generalNotes([...(nv?.notes ?? []), ...(notes ?? [])]).filter((n, i, a) => a.findIndex((m) => m.code === n.code) === i);
  return (
    <Card span={9} step="④" title="변수 범위" aside={<span className="muted small">{engine === "altair" ? "범위 자유 · 학습 범위 밖은 경고 · 하한 = 상한이면 고정" : "범위 자유 · 학습 범위·모핑 가능 범위 밖은 경고 · 하한 = 상한이면 고정"}</span>}>
      <NativeVarsTable label="변수 범위" engine={engine} rows={rows} canEdit={canEdit} showFixed notes={notes} onPatch={onPatch} onBulkUse={onBulkUse} onRemove={onRemove} />
      <div className="run-action-row small">
        {canEdit && pool.length > 0 && (
          <select value="" aria-label="변수 추가" onChange={(e) => e.target.value && onAdd(e.target.value)}>
            <option value="">변수 추가…</option>
            {pool.map((p) => (
              <option key={p.name} value={p.name}>
                {engine === "altair" ? p.name : `${p.name} · ${typeLabel(p.type ?? "")} · ${p.body ?? ""}`}
              </option>
            ))}
          </select>
        )}
        <span className="muted" data-testid="vars-run-note">이 실행에만 적용(세트 정의는 ④에서). {engine === "altair" ? "목록에 없는 변수는 ①-2에서 tpl을 다시 생성해 새 템플릿으로 등록하세요." : "목록에 없는 변수는 추출 조건을 바꿔 새 템플릿으로 등록하세요."}</span>
      </div>
      {info.map((n) => (
        <p key={n.code} className="muted small" data-testid={`var-note-${n.code}`}>
          {n.message}
        </p>
      ))}
    </Card>
  );
}
