// ④ "형상 템플릿" 드롭다운(phase3.md §14.8): 템플릿 = 이름 붙은 파라미터 세트(§13 label). 고른 템플릿이 예측 요청의 param_set_id가 된다.
import { useEffect, useState } from "react";
import type { InputKind, ParamSet } from "../../api";
import { useStudy } from "../../app/StudyContext";

export function templateName(ps: ParamSet): string {
  return ps.label || ps.source_path.split(/[\\/]/).filter(Boolean).pop() || ps.id;
}

export function inputKindOf(ps: ParamSet): InputKind {
  return ps.input_kind ?? "assembly";
}

export const INPUT_KIND_LABEL: Record<InputKind, string> = {
  assembly: "조립 폴더 포함",
  mesh_only: "조립 폴더 없음(메시 단독)",
};

function mmdd(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** 옆 회색 한 줄: tpl · CAD · 조립 폴더 포함 · MM-DD 등록 */
export function templateMeta(ps: ParamSet): string {
  return ["tpl", "CAD", INPUT_KIND_LABEL[inputKindOf(ps)], `${mmdd(ps.registered_at)} 등록`].join(" · ");
}

export function TemplatePicker({ list, value, onChange, compact = false }: { list: ParamSet[]; value: string; onChange: (id: string) => void; compact?: boolean }) {
  const ps = list.find((p) => p.id === value) ?? null;
  return (
    <div className={compact ? "tpl-pick compact" : "tpl-pick"}>
      <label className="tpl-pick-field">
        <span className="field-label">형상 템플릿</span>
        <select value={value} onChange={(e) => onChange(e.target.value)} disabled={!list.length}>
          {!list.length && <option value="">등록된 템플릿 없음</option>}
          {list.map((p) => (
            <option key={p.id} value={p.id}>
              {templateName(p)} — {p.parameters.length}개 파라미터
            </option>
          ))}
        </select>
      </label>
      {ps && (
        <span className="muted small" data-testid="template-meta">
          {templateMeta(ps)}
        </span>
      )}
    </div>
  );
}

/** 고른 템플릿(기본 = 현재 세트). 새로 등록하면 그 템플릿으로 바뀐다 */
export function useTemplateChoice() {
  const { paramSets, currentParamSet } = useStudy();
  const [picked, setPicked] = useState<string>(currentParamSet?.id ?? paramSets[0]?.id ?? "");
  useEffect(() => {
    if (currentParamSet) setPicked(currentParamSet.id);
  }, [currentParamSet?.id]);
  const ps = paramSets.find((p) => p.id === picked) ?? currentParamSet ?? paramSets[0] ?? null;
  return { list: paramSets, ps, setPicked };
}

