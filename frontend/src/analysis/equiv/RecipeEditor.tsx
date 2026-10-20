// ⑤ 등가성 판정 — 레시피 편집 표(equiv-check.md §7-2, 접힘): 지표 행(사용·이름·종류·원천 연결·상대%·절대·상관 하한·필수/참고).
// 연결 필요 행은 노란 표시. 버튼(이번만 사용·새 버전 저장·다른 이름으로 저장·삭제)은 EquivTab이 판단해 넘긴다.
import { useState } from "react";
import type { EqKind, EqSource } from "../../api/equivCheck";
import { KIND_LABEL, numOrNull, sourceText, type EditRow } from "./recipeState";

export interface RecipeEditorProps {
  rows: EditRow[];
  onChange: (rows: EditRow[]) => void;
  /** 양쪽 결과 집합에 있는 성능 정의 이름(원천 연결 드롭다운) */
  perfNames: string[];
  readonly: boolean;
  pairRule: { mode: "all" | "min_ratio"; ratio?: number };
  onPairRule: (r: { mode: "all" | "min_ratio"; ratio?: number }) => void;
}

const SOURCE_KINDS: Record<EqKind, { value: string; label: string }[]> = {
  scalar: [
    { value: "perf", label: "성능 정의" },
    { value: "h3d", label: "H3D 직접 지정" },
    { value: "curve", label: "곡선 통계" },
  ],
  curve_corr: [{ value: "curve", label: "곡선" }],
  curve_nrmse: [{ value: "curve", label: "곡선" }],
  mesh_volume: [{ value: "mesh_volume", label: "메시 부피" }],
};

function defaultSource(kind: EqKind, type: string, perfNames: string[]): EqSource | null {
  if (type === "") return null;
  if (type === "perf") return perfNames[0] ? { type: "perf", perf: perfNames[0] } : null;
  if (type === "h3d") return { type: "h3d", subcase: 1, datatype: "", component: "", layer: "", stat: "MAX" };
  if (type === "curve") return kind === "scalar" ? { type: "curve", series: null, stat: "ABSMAX" } : { type: "curve", series: null, t01: null };
  return { type: "mesh_volume", parts: "cushion", origin: "mesh" };
}

export function SourceField({ row, perfNames, disabled, onChange }: { row: EditRow; perfNames: string[]; disabled: boolean; onChange: (s: EqSource | null) => void }) {
  const kinds = SOURCE_KINDS[row.kind];
  const t = row.source?.type ?? "";
  const s = row.source;
  return (
    <div className={`eq-src${!s && row.kind !== "mesh_volume" ? " unbound" : ""}`} data-testid={`eq-src-${row.id}`}>
      {row.kind !== "mesh_volume" && (
        <select aria-label={`${row.label} 원천 종류`} value={t} disabled={disabled} onChange={(e) => onChange(defaultSource(row.kind, e.target.value, perfNames))}>
          <option value="">연결 필요</option>
          {kinds.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      )}
      {s?.type === "perf" && (
        <select aria-label={`${row.label} 성능 정의`} value={s.perf} disabled={disabled} onChange={(e) => onChange({ type: "perf", perf: e.target.value })}>
          {!perfNames.includes(s.perf) && <option value={s.perf}>{s.perf}</option>}
          {perfNames.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      )}
      {s?.type === "h3d" && (
        <>
          <input aria-label={`${row.label} datatype`} placeholder="datatype" value={s.datatype} disabled={disabled} onChange={(e) => onChange({ ...s, datatype: e.target.value })} />
          <input aria-label={`${row.label} component`} placeholder="component" value={s.component ?? ""} disabled={disabled} onChange={(e) => onChange({ ...s, component: e.target.value })} />
          <select aria-label={`${row.label} stat`} value={s.stat ?? "MAX"} disabled={disabled} onChange={(e) => onChange({ ...s, stat: e.target.value as "MAX" | "MIN" | "ABSMAX" })}>
            <option>MAX</option>
            <option>MIN</option>
            <option>ABSMAX</option>
          </select>
        </>
      )}
      {s?.type === "curve" && (
        <>
          <input aria-label={`${row.label} 계열`} placeholder="계열(비우면 첫 계열)" value={s.series ?? ""} disabled={disabled} onChange={(e) => onChange({ ...s, series: e.target.value.trim() || null })} />
          {row.kind === "scalar" && (
            <select aria-label={`${row.label} stat`} value={s.stat ?? "MAX"} disabled={disabled} onChange={(e) => onChange({ ...s, stat: e.target.value as "MAX" | "MIN" | "ABSMAX" })}>
              <option>MAX</option>
              <option>MIN</option>
              <option>ABSMAX</option>
            </select>
          )}
        </>
      )}
      {row.kind === "mesh_volume" && (
        <select aria-label={`${row.label} 부피 원천`} value={s?.type === "mesh_volume" ? s.origin ?? "mesh" : "mesh"} disabled={disabled} onChange={(e) => onChange({ type: "mesh_volume", parts: s?.type === "mesh_volume" ? s.parts : "cushion", origin: e.target.value as "mesh" | "starter_mass" | "paicad" })}>
          <option value="mesh">메시 include 적분</option>
          <option value="starter_mass">starter 질량</option>
          <option value="paicad">paicad 보고값</option>
        </select>
      )}
      <span className="muted small eq-src-text">{sourceText(s ?? (row.kind === "mesh_volume" ? { type: "mesh_volume", parts: "cushion" } : null))}</span>
    </div>
  );
}

export function RecipeEditor({ rows, onChange, perfNames, readonly, pairRule, onPairRule }: RecipeEditorProps) {
  const [adding, setAdding] = useState(false);
  const [newId, setNewId] = useState("");
  const [newKind, setNewKind] = useState<EqKind>("scalar");
  const upd = (i: number, patch: Partial<EditRow>) => onChange(rows.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  const tol = (i: number, key: keyof EditRow["tol"], v: string) => upd(i, { tol: { ...rows[i].tol, [key]: numOrNull(v) ?? (v.trim() === "" ? null : rows[i].tol[key]) } });
  const add = () => {
    const id = newId.trim();
    if (!/^[a-z][a-z0-9_]{0,31}$/.test(id) || rows.some((r) => r.id === id)) return;
    const base: EditRow = { id, label: id, kind: newKind, source: newKind === "mesh_volume" ? { type: "mesh_volume", parts: "cushion", origin: "mesh" } : null, tol: newKind === "curve_corr" ? { corr_min: 0.95 } : newKind === "curve_nrmse" ? { nrmse_max_pct: 5 } : { rel_pct: 5, abs: null }, required: true, use: true };
    onChange([...rows, base]);
    setNewId("");
    setAdding(false);
  };
  return (
    <div className="eq-editor" data-testid="eq-recipe-editor">
      <table className="table compact" aria-label="레시피 지표">
        <thead>
          <tr>
            <th>사용</th>
            <th>이름</th>
            <th>종류</th>
            <th>원천 연결</th>
            <th>상대 %</th>
            <th>절대값</th>
            <th>상관 하한 / NRMSE 상한</th>
            <th>구분</th>
            {!readonly && <th />}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id} className={!r.source && r.kind !== "mesh_volume" ? "eq-row-unbound" : ""} data-testid={`eq-row-${r.id}`}>
              <td>
                <input type="checkbox" aria-label={`${r.label} 사용`} checked={r.use} disabled={readonly} onChange={(e) => upd(i, { use: e.target.checked })} />
              </td>
              <td>
                <input aria-label={`${r.id} 이름`} value={r.label} maxLength={40} disabled={readonly} onChange={(e) => upd(i, { label: e.target.value })} />
                <span className="muted small"> {r.id}</span>
              </td>
              <td>{KIND_LABEL[r.kind]}</td>
              <td>
                <SourceField row={r} perfNames={perfNames} disabled={readonly} onChange={(s) => upd(i, { source: s })} />
              </td>
              <td>{r.kind === "scalar" || r.kind === "mesh_volume" ? <input className="num-input" inputMode="decimal" aria-label={`${r.label} 상대 %`} value={r.tol.rel_pct ?? ""} disabled={readonly} onChange={(e) => tol(i, "rel_pct", e.target.value)} /> : "—"}</td>
              <td>{r.kind === "scalar" || r.kind === "mesh_volume" ? <input className="num-input" inputMode="decimal" aria-label={`${r.label} 절대값`} value={r.tol.abs ?? ""} disabled={readonly} onChange={(e) => tol(i, "abs", e.target.value)} /> : "—"}</td>
              <td>
                {r.kind === "curve_corr" && <input className="num-input" inputMode="decimal" aria-label={`${r.label} 상관 하한`} value={r.tol.corr_min ?? ""} disabled={readonly} onChange={(e) => tol(i, "corr_min", e.target.value)} />}
                {r.kind === "curve_nrmse" && <input className="num-input" inputMode="decimal" aria-label={`${r.label} NRMSE 상한`} value={r.tol.nrmse_max_pct ?? ""} disabled={readonly} onChange={(e) => tol(i, "nrmse_max_pct", e.target.value)} />}
                {(r.kind === "scalar" || r.kind === "mesh_volume") && "—"}
              </td>
              <td>
                <select aria-label={`${r.label} 구분`} value={r.required ? "required" : "reference"} disabled={readonly} onChange={(e) => upd(i, { required: e.target.value === "required" })}>
                  <option value="required">필수</option>
                  <option value="reference">참고</option>
                </select>
              </td>
              {!readonly && (
                <td>
                  <button type="button" className="btn ghost small" aria-label={`${r.label} 지표 제거`} onClick={() => onChange(rows.filter((_x, k) => k !== i))}>
                    ×
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {!readonly && (
        <div className="eq-editor-foot">
          <label className="inline-field">
            쌍 집계
            <select aria-label="쌍 집계 규칙" value={pairRule.mode} onChange={(e) => onPairRule(e.target.value === "min_ratio" ? { mode: "min_ratio", ratio: pairRule.ratio ?? 0.9 } : { mode: "all" })}>
              <option value="all">모든 쌍 통과</option>
              <option value="min_ratio">통과 비율 이상</option>
            </select>
          </label>
          {pairRule.mode === "min_ratio" && <input className="num-input" inputMode="decimal" aria-label="통과 비율" value={pairRule.ratio ?? 0.9} onChange={(e) => onPairRule({ mode: "min_ratio", ratio: numOrNull(e.target.value) ?? 0.9 })} />}
          {adding ? (
            <span className="eq-add">
              <input aria-label="새 지표 id" placeholder="id(소문자·숫자·_)" value={newId} onChange={(e) => setNewId(e.target.value)} />
              <select aria-label="새 지표 종류" value={newKind} onChange={(e) => setNewKind(e.target.value as EqKind)}>
                {(Object.keys(KIND_LABEL) as EqKind[]).map((k) => (
                  <option key={k} value={k}>
                    {KIND_LABEL[k]}
                  </option>
                ))}
              </select>
              <button type="button" className="btn ghost small" onClick={add}>
                추가
              </button>
              <button type="button" className="btn ghost small" onClick={() => setAdding(false)}>
                취소
              </button>
            </span>
          ) : (
            <button type="button" className="btn ghost small" onClick={() => setAdding(true)}>
              지표 추가
            </button>
          )}
        </div>
      )}
    </div>
  );
}
