// 하이라이트 그림(그림 탭·3D 폴백): 선택 변수의 PNG. 0개 = 안내 + 첫 변수 보기, 1개 = 그 PNG, 여럿 = 격자(최대 8, 범례 색 테두리).
// PNG 로드 실패(401·404·410·네트워크)는 원인 + [다시 시도]로 보인다.
import { API_PREFIX } from "../../../api";
import { useMediaImageState } from "../ContourMedia";
import { selectionColor } from "./viewerCore";

export const MAX_PNG_GRID = 8;

/** 하이라이트 PNG(§4.3 features/<NAME>.png → FEATURE_PNG artifact). 이미지는 fetch → blob URL(목·쿠키 인증 같은 길) */
export function FeaturePng({ name, artifactId, color }: { name: string; artifactId: string; color?: string }) {
  const { src, error, retry } = useMediaImageState(`${API_PREFIX}/artifacts/${artifactId}/media`);
  return (
    <figure className="feature-png" data-testid="feature-png" style={color ? { borderColor: color } : undefined}>
      {src && <img src={src} alt={`${name} 하이라이트`} />}
      {error && (
        <div className="small error-text" role="alert" data-testid="png-error">
          그림을 불러오지 못했습니다({error}){" "}
          <button type="button" className="link small" onClick={retry}>
            다시 시도
          </button>
        </div>
      )}
      <figcaption className="small muted mono">{name}</figcaption>
    </figure>
  );
}

export function PngGrid({
  rows,
  pngOf,
  firstRow,
  onRows,
}: {
  rows: string[];
  /** 행 → 하이라이트 PNG artifact id(없으면 null) */
  pngOf: (row: string) => string | null;
  /** 선택이 없을 때 [첫 변수 보기]로 고를 행 */
  firstRow?: string | null;
  onRows?: (rows: string[], focus?: string | null) => void;
}) {
  if (!rows.length) {
    return (
      <div className="gv-png-empty small muted" data-testid="png-empty">
        <p>표에서 변수를 클릭하면 하이라이트 그림(이동 면 주황·고정 면 파랑)을 봅니다. Ctrl/⌘ 클릭 = 여러 개, Shift 클릭 = 범위.</p>
        {firstRow && onRows && (
          <button type="button" className="btn small ghost" onClick={() => onRows([firstRow], firstRow)}>
            첫 변수 보기
          </button>
        )}
      </div>
    );
  }
  const shown = rows.slice(0, MAX_PNG_GRID);
  const multi = rows.length > 1;
  return (
    <div className="gv-png-wrap">
      <div className={multi ? "gv-png-grid" : "gv-png-single"} data-testid="png-grid">
        {shown.map((r, i) => {
          const id = pngOf(r);
          return id ? (
            <FeaturePng key={r} name={r} artifactId={id} color={multi ? selectionColor(i) : undefined} />
          ) : (
            <figure key={r} className="feature-png" style={multi ? { borderColor: selectionColor(i) } : undefined}>
              <div className="small muted">그림 없음(3D 하이라이트 대상이 아닌 변수)</div>
              <figcaption className="small muted mono">{r}</figcaption>
            </figure>
          );
        })}
      </div>
      {rows.length > MAX_PNG_GRID && <p className="small muted">외 {rows.length - MAX_PNG_GRID}개는 표시하지 않습니다(최대 {MAX_PNG_GRID}개)</p>}
    </div>
  );
}
