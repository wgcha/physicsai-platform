// ⑤ 등가성 판정 — 비교 대상(side) 선택(equiv-check.md §4.1·§7-1): 종류 4가지(해석 DOE·일괄 예측·FEM 검증·폴더) + 대상 드롭다운/경로 목록.
import type { PredictBatchSummary, TrainDoe } from "../../api";
import type { EqSideReq } from "../../api/equivCheck";
import type { FemVerifySummary } from "../../api/femVerify";
import { BrowseButton } from "../../components/BrowseButton";

export type SideKind = EqSideReq["kind"];
export interface SideSel {
  kind: SideKind;
  id: string;
  paths: string;
}

export const KIND_LABEL: Record<SideKind, string> = { train_doe: "해석 DOE(①)", predict_batch: "일괄 예측(④)", fem_verify: "FEM 검증", folder: "폴더(서버 경로)" };

export const emptySide = (kind: SideKind = "train_doe"): SideSel => ({ kind, id: "", paths: "" });

export function toSideReq(s: SideSel): EqSideReq | null {
  if (s.kind === "folder") {
    const paths = s.paths.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
    return paths.length ? { kind: "folder", paths } : null;
  }
  if (!s.id) return null;
  if (s.kind === "train_doe") return { kind: "train_doe", doe_id: s.id };
  if (s.kind === "predict_batch") return { kind: "predict_batch", batch_id: s.id };
  return { kind: "fem_verify", fv_id: s.id };
}

export function SidePicker({ slot, sel, onChange, batches, does, fems, disabled }: { slot: string; sel: SideSel; onChange: (s: SideSel) => void; batches: PredictBatchSummary[]; does: TrainDoe[]; fems: FemVerifySummary[]; disabled?: boolean }) {
  const kinds = Object.keys(KIND_LABEL) as SideKind[];
  const options: { id: string; label: string }[] =
    sel.kind === "train_doe"
      ? does.filter((d) => d.status === "READY").map((d) => ({ id: d.id, label: `${d.doe_label} · run ${d.run_count ?? "?"}` }))
      : sel.kind === "predict_batch"
        ? batches.filter((b) => b.status === "DONE").map((b) => ({ id: b.id, label: `${b.label} · run ${b.run_count}` }))
        : sel.kind === "fem_verify"
          ? fems.filter((f) => f.status === "DONE").map((f) => ({ id: f.id, label: `${f.label} · ${f.source_label}` }))
          : [];
  return (
    <div className="eq-side" role="group" aria-label={`${slot} 대상`} data-testid={`eq-side-${slot}`}>
      <span className="eq-side-slot">{slot}</span>
      <select aria-label={`${slot} 종류`} value={sel.kind} disabled={disabled} onChange={(e) => onChange(emptySide(e.target.value as SideKind))}>
        {kinds.map((k) => (
          <option key={k} value={k}>
            {KIND_LABEL[k]}
          </option>
        ))}
      </select>
      {sel.kind === "folder" ? (
        <div className="eq-side-paths">
          <textarea aria-label={`${slot} 폴더 경로`} rows={2} placeholder={"run 폴더 경로(줄마다 1개) — 직계 h3d·T01 각 1개, 선택 params.json"} value={sel.paths} disabled={disabled} onChange={(e) => onChange({ ...sel, paths: e.target.value })} />
          <BrowseButton mode="dir" disabled={disabled} onPick={(p) => onChange({ ...sel, paths: sel.paths.trim() ? `${sel.paths.trimEnd()}\n${p}` : p })} title={`${slot} run 폴더 선택`} />
        </div>
      ) : (
        <select aria-label={`${slot} 대상 선택`} value={sel.id} disabled={disabled} onChange={(e) => onChange({ ...sel, id: e.target.value })}>
          <option value="">— 선택 —</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
