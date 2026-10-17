// ⑤ 출처 선택(phase3.md §19.7): 세그먼트 `일괄 예측 결과(예측)` | `해석 DOE 결과(해석)` + 출처 드롭다운(라벨·run 수·날짜). 기본·비교 두 슬롯이 같은 컴포넌트를 쓴다.
// 마지막 선택은 브라우저별 기억(localStorage physicsai.analysis.source, try/catch). 쿼리(?source=batch&id=…|?source=doe&id=…)가 있으면 쿼리 우선.
import type { PredictBatchSummary, TrainDoe } from "../../api";
import { fmtTime } from "../../lib/format";
import type { SourceKind } from "./useResultTable";

export const SOURCE_KEY = "physicsai.analysis.source";
export const SEGMENTS: { key: SourceKind; label: string }[] = [
  { key: "batch", label: "일괄 예측 결과(예측)" },
  { key: "doe", label: "해석 DOE 결과(해석)" },
];
export const EMPTY_TEXT = "④에서 일괄 예측을 실행하거나 ①에서 해석 DOE 결과를 만드세요";

export interface SourceSel {
  kind: SourceKind;
  id: string;
}

export function readSource(): SourceSel | null {
  try {
    const v = JSON.parse(globalThis.localStorage?.getItem(SOURCE_KEY) ?? "null") as Record<string, unknown> | null;
    if (v && (v.kind === "batch" || v.kind === "doe") && typeof v.id === "string") return { kind: v.kind, id: v.id };
    if (v && (v.kind === "batch" || v.kind === "doe")) return { kind: v.kind, id: "" };
  } catch {
    /* 저장값 없음·손상 */
  }
  return null;
}

export function writeSource(s: SourceSel) {
  try {
    globalThis.localStorage?.setItem(SOURCE_KEY, JSON.stringify(s));
  } catch {
    /* 저장 실패는 무시 */
  }
}

/** 드롭다운에 오르는 출처: 완료 배치(+ 지금 고른 것) · 준비된(READY) DOE */
export function batchOptions(list: PredictBatchSummary[], currentId: string | null): PredictBatchSummary[] {
  return list.filter((b) => b.status === "DONE" || b.id === currentId);
}
export function doeOptions(list: TrainDoe[], currentId: string | null): TrainDoe[] {
  return list.filter((d) => d.status === "READY" || d.id === currentId);
}

export function SourcePicker({ slot, sel, batches, does, onChange }: { slot: string; sel: SourceSel; batches: PredictBatchSummary[]; does: TrainDoe[]; onChange: (s: SourceSel) => void }) {
  const bs = batchOptions(batches, sel.kind === "batch" ? sel.id : null);
  const ds = doeOptions(does, sel.kind === "doe" ? sel.id : null);
  const first = (k: SourceKind) => (k === "batch" ? bs[0]?.id : ds[0]?.id) ?? "";
  return (
    <>
      <div className="seg" role="group" aria-label={`${slot} 출처`}>
        {SEGMENTS.map((x) => (
          <button key={x.key} type="button" className={sel.kind === x.key ? "on" : ""} aria-pressed={sel.kind === x.key} onClick={() => sel.kind !== x.key && onChange({ kind: x.key, id: first(x.key) })}>
            {x.label}
          </button>
        ))}
      </div>
      <label className="inline-field small">
        {slot} 출처
        <select value={sel.id} aria-label={`${slot} 출처 선택`} onChange={(e) => onChange({ kind: sel.kind, id: e.target.value })}>
          {!sel.id && <option value="">선택…</option>}
          {sel.kind === "batch"
            ? bs.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.label} · run {b.run_count} · {fmtTime(b.created_at)}
                  {b.status !== "DONE" ? " · 진행 중" : ""}
                </option>
              ))
            : ds.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.doe_label} · run {d.run_count ?? "–"} · {fmtTime(d.created_at)}
                </option>
              ))}
        </select>
      </label>
    </>
  );
}
