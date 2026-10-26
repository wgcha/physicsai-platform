// 격자 셀 1개(doe-preview.md §7): 320×240 PNG(1:1) + 캡션 2줄(run·최대 변위 / 바뀐 변수 상위 3) + 상태 표시.
// 실패 = 빨간 2px 테두리 + 배지 + 사유 한 줄, 오류 = 회색 점선 + [다시], 공칭 = 회색 점선 테두리, 생성 후 겹침 = 우상단 배지.
import { API_PREFIX } from "../../../api";
import type { DoePreviewCell } from "../../../api/types";
import { useMediaImageState } from "../../stage4/ContourMedia";
import { MSG, cellLabel, cellTone, changeText, failInfo, genBadge, overRange, valuesTip } from "./gridModel";

export function GridCell({ cell, gallery, range, onOpen, onRetry }: { cell: DoePreviewCell; gallery: boolean; range: [number, number] | undefined; onOpen: (c: DoePreviewCell) => void; onRetry: () => void }) {
  const tone = cellTone(cell);
  const img = useMediaImageState(cell.png_artifact_id ? `${API_PREFIX}/artifacts/${cell.png_artifact_id}/media` : null);
  const fail = failInfo(cell);
  const gen = genBadge(cell.gen);
  const label = cellLabel(cell, gallery);
  const clickable = (cell.status === "OK" || cell.status === "FAIL") && !!cell.png_artifact_id;
  const open = () => clickable && onOpen(cell);
  return (
    <div
      className={`dp-cell ${tone}`}
      data-testid={`dp-cell-${cell.nominal ? "nominal" : cell.doe_no}`}
      data-status={cell.status}
      title={valuesTip(cell)}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      aria-label={clickable ? `${label} 형상 열기` : undefined}
      onClick={open}
      onKeyDown={(e) => {
        if (clickable && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          open();
        }
      }}
    >
      <div className="dp-img">
        {img.src && <img src={img.src} alt={`${label} 형상`} width={320} height={240} />}
        {!img.src && cell.status === "PENDING" && <span className="muted small">만드는 중…</span>}
        {img.error && (
          <span className="small error-text" role="alert">
            그림을 불러오지 못했습니다({img.error})
          </span>
        )}
        {gen && (
          <span className={`pill dp-gen ${gen.tone}`} data-testid="dp-gen" title={MSG.genDiff}>
            {gen.text}
          </span>
        )}
        {cell.clipped && <span className="pill dp-clip small">잘림</span>}
        {overRange(cell, range) && <span className="pill warn dp-over small">▲범위 초과</span>}
      </div>
      <div className="dp-cap small">
        <div className="dp-cap1">
          <b className="mono">{label}</b>
          {cell.max_disp_mm != null && cell.status !== "PENDING" && <span className="muted"> · 최대 {Number(cell.max_disp_mm.toFixed(2))} mm</span>}
        </div>
        {fail ? (
          <div className="dp-fail" data-testid="dp-fail">
            <span className="pill bad">{fail.badge}</span> {fail.text}
          </div>
        ) : cell.status === "ERROR" ? (
          <div className="dp-err">
            <button
              type="button"
              className="link small"
              onClick={(e) => {
                e.stopPropagation();
                onRetry();
              }}
            >
              {MSG.errorCell}
            </button>
          </div>
        ) : (
          <div className="dp-cap2 muted">{changeText(cell)}</div>
        )}
      </div>
    </div>
  );
}
