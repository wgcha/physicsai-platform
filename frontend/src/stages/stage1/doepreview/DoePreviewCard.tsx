// DOE 형상 그리드 미리보기 카드(doe-preview.md §7·§8): ①-3 DOE 카드 바로 아래 전폭 카드 1개 — 툴바 1줄 + 범례 + 격자(6×4 = 24셀, 첫 셀 = 공칭).
// 생성 전(source train·param_set)은 "미리보기", 생성 후(train_doe)는 "형상 갤러리"(같은 격자 + 스킵 배지). 격자는 서버 PNG라 WebGL 없이도 동작한다.
import { useEffect, useMemo, useState } from "react";
import type { DoePreviewCell } from "../../../api/types";
import { Card, ProgressBar } from "../../../components/ui";
import { fmtLegend, legendTicks } from "../../stage4/geomview/contour/colormap";
import { Seg } from "../DoePlatformFields";
import { CellDialog } from "./CellDialog";
import { GridCell } from "./GridCell";
import { MSG, ORDER_LABEL, PAGE_SIZE, filterFailed, turbo16Gradient, hasMore, inputKey, isActive, mergeCells, progressOf, progressText } from "./gridModel";
import { useDoePreviewGrid, type GridInput, type GridSelect } from "./useDoePreviewGrid";
import type { DoePreviewOrder } from "../../../api/types";

const HEAD_TEXT = { pre: "형상 미리보기", gallery: "형상 갤러리" } as const;

export function DoePreviewCard({ studyId, gallery, input, names, canRun, onClose }: { studyId: string; gallery: boolean; input: GridInput | null; names: string[]; canRun: boolean; onClose: () => void }) {
  const g = useDoePreviewGrid(studyId);
  const [sel, setSel] = useState<GridSelect>({ order: "change", var: null, desc: false });
  const [requested, setRequested] = useState<string | null>(null);
  const [failedOnly, setFailedOnly] = useState(false);
  const [open, setOpen] = useState<DoePreviewCell | null>(null);

  const start = (s: GridSelect) => {
    if (!input) return;
    setRequested(inputKey(input.source, input.sampling));
    void g.load(input, s);
  };
  // 열 때 한 번 요청한다(카드가 열려 있는 동안 입력이 바뀌면 낡음 표시 — 자동 재요청 없음)
  useEffect(() => {
    start(sel);
    return () => g.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changeSel = (next: GridSelect) => {
    setSel(next);
    start(next);
  };
  const pickOrder = (order: DoePreviewOrder) => changeSel({ ...sel, order, var: order === "var" ? sel.var ?? names[0] ?? null : sel.var });

  const first = g.pages[0]?.pv ?? null;
  const cells = useMemo(() => mergeCells(g.pages.map((p) => p.pv)), [g.pages]);
  const shown = filterFailed(cells, failedOnly);
  const nominal = cells.find((c) => c.nominal) ?? null;
  const prog = progressOf(cells);
  const running = g.pages.some((p) => isActive(p.pv));
  const stale = requested != null && (!input || inputKey(input.source, input.sampling) !== requested);
  const range = first?.disp_range_mm ?? undefined;
  const canceled = g.pages.some((p) => p.pv.status === "CANCELED");
  const failedJob = g.pages.find((p) => p.pv.status === "FAILED");
  const queued = g.pages.map((p) => p.pv.queue).find((q) => !!q) ?? null;
  const partial = g.pages.some((p) => p.pv.warnings?.some((w) => w.code === "DOE_PREVIEW_PARTIAL"));
  const retryOffset = (cell: DoePreviewCell) => g.pages.find((p) => p.pv.cells.includes(cell))?.offset ?? 0;

  return (
    <Card span={12} step="①-3" title={HEAD_TEXT[gallery ? "gallery" : "pre"]} className="dp-card">
      <div className="dp-toolbar run-action-row" data-testid="dp-toolbar">
        <Seg
          label="정렬"
          value={sel.order}
          options={(["change", "doe", "var"] as const).map((k) => ({ key: k, label: ORDER_LABEL[k], disabled: k === "var" && !names.length }))}
          onChange={pickOrder}
          disabled={!canRun || !input}
        />
        {sel.order === "var" && (
          <>
            <select aria-label="정렬 변수" value={sel.var ?? ""} disabled={!canRun} onChange={(e) => changeSel({ ...sel, var: e.target.value })}>
              {names.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            <button type="button" className="btn small ghost" aria-label={sel.desc ? "내림차순" : "오름차순"} title={sel.desc ? "내림차순" : "오름차순"} disabled={!canRun} onClick={() => changeSel({ ...sel, desc: !sel.desc })}>
              {sel.desc ? "↓" : "↑"}
            </button>
          </>
        )}
        <label className="check small" title="이미 만들어진 셀 중 실패·오류만 봅니다">
          <input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} /> 실패만
        </label>
        <span className="small muted" data-testid="dp-progress">
          {cells.length ? progressText(prog) : g.busy ? "요청 중…" : ""}
          {first && ` · 전체 ${first.n_total}개 중`}
        </span>
        <span className="dp-spacer" />
        {running && (
          <button type="button" className="btn small" disabled={!canRun} onClick={() => void g.cancel()}>
            취소
          </button>
        )}
        <button type="button" className="btn small" disabled={!canRun || running || g.busy || !hasMore(g.pages.map((p) => p.pv))} onClick={() => void g.next()}>
          다음 {PAGE_SIZE}개
        </button>
        <button type="button" className="btn small ghost" onClick={onClose}>
          닫기
        </button>
      </div>
      {running && <ProgressBar pct={cells.length ? Math.round((prog.done / Math.max(1, prog.total)) * 100) : null} label="형상 미리보기 진행률" />}
      {queued && !cells.some((c) => c.status !== "PENDING") && (
        <p className="small muted" data-testid="dp-queue">
          CPU 대기열에서 대기 중({queued.position}번째)
        </p>
      )}
      {stale && (
        <p className="small warn-text" role="status" data-testid="dp-stale">
          {MSG.stale} —{" "}
          <button type="button" className="link small" disabled={!canRun || !input} onClick={() => start(sel)}>
            다시 미리보기
          </button>
        </p>
      )}
      {g.error && (
        <p className="small error-text" role="alert" data-testid="dp-error">
          {g.error}
        </p>
      )}
      {failedJob && !cells.some((c) => c.status === "OK") && (
        <p className="small error-text" role="alert">
          형상 미리보기에 실패했습니다
        </p>
      )}
      {canceled && !running && <p className="small muted">취소했습니다 — 이미 만든 셀은 남습니다</p>}
      {partial && <p className="small warn-text">일부 셀을 만들지 못했습니다 — 오류 셀의 [다시]를 누르세요</p>}
      {range && (
        <div className="dp-legend small" data-testid="dp-legend" aria-label="변위 범례">
          <span>{MSG.legendTitle}</span>
          <span className="dp-legend-bar" style={{ background: turbo16Gradient() }} data-colormap="turbo16" />
          <span className="dp-legend-ticks mono">
            {legendTicks(range[0], range[1], 3).reverse().map((t, i) => (
              <span key={i}>{fmtLegend(t)}</span>
            ))}
          </span>
        </div>
      )}
      {first?.tag_state === "none" && !gallery && (
        <p className="small muted" data-testid="dp-tag-note">
          {MSG.tagNone}
        </p>
      )}
      <div className={`dp-grid${stale ? " stale" : ""}`} data-testid="dp-grid">
        {shown.map((c) => (
          <GridCell key={c.nominal ? "nominal" : `d${c.doe_no}`} cell={c} gallery={gallery} range={range} onOpen={setOpen} onRetry={() => void g.retry(retryOffset(c))} />
        ))}
      </div>
      {failedOnly && !shown.length && cells.length > 0 && <p className="small muted">만들어진 셀 중 실패한 셀이 없습니다</p>}
      {open && range && <CellDialog cell={open} nominal={nominal} range={range} gallery={gallery} onClose={() => setOpen(null)} />}
    </Card>
  );
}
