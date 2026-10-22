// ⑤ 결과 컨투어 칸(contour3d-default C3D-10): 결과 표 옆 별도 카드(1:1), 선택 행(selected)의 3D 컨투어. 행 선택은 0.8초 머문 뒤 요청한다.
// 일괄 배치 행 = PREDICT_H3D {job_id}(PNG·영상은 [그림/영상] 창), 해석 DOE 행 = SOLVER_H3D {study_id, h3d_rel}(runs 페이지 맵, PNG 없음 → 버튼 숨김).
import { useStudy } from "../../app/StudyContext";
import { Card } from "../../components/ui";
import { useRunH3dMap } from "../../hooks/useRunH3dMap";
import { useCanExecute } from "../../hooks/useJobRunner";
import { POLL } from "../../lib/poll";
import { isOkState, type ResultTable } from "../../analysis/resultTable";
import { ContourMedia } from "../stage4/ContourMedia";
import { ContourSlot } from "../stage4/geomview/contour/ContourSlot";
import type { Contour3dCreate } from "../../api";

export const NO_H3D_TEXT = "이 run은 결과 h3d가 없습니다";
export const NO_3D_TEXT = "이 PC에서는 3D 컨투어를 볼 수 없습니다(WebGL 또는 기능 꺼짐)";

export function AnalysisContourCard({ table, selected }: { table: ResultTable; selected: number | null }) {
  const { study } = useStudy();
  const canCapture = useCanExecute();
  const batch = table.origin.kind === "predict_batch";
  const h3d = useRunH3dMap(batch ? null : table.origin.id);
  const row = table.rows.find((r) => r.no === selected) ?? null;
  let source: Contour3dCreate | null = null;
  let note = "표에서 run을 고르세요.";
  if (row) {
    if (batch) {
      if (isOkState(row.state) && row.job_id) source = { source_kind: "PREDICT_H3D", source_ref: { job_id: row.job_id } };
      else note = "이 run은 예측이 끝나지 않았습니다";
    } else if (h3d.error) note = h3d.error;
    else if (!h3d.map) note = "불러오는 중…";
    else {
      const rel = h3d.map.get(row.run_id);
      if (rel) source = { source_kind: "SOLVER_H3D", source_ref: { study_id: study.id, h3d_rel: rel } };
      else note = NO_H3D_TEXT;
    }
  }
  const media = batch && source && row?.job_id ? <ContourMedia key={row.job_id} jobId={row.job_id} canCapture={canCapture} /> : null;
  return (
    <ContourSlot source={source} media={media} mediaTitle={row ? `그림/영상 — DOE #${row.no}` : undefined} delayMs={POLL.contourDwell}>
      {({ aside, body, mode }) => (
        <Card span="half" title="결과 컨투어" step={row ? `DOE #${row.no}` : undefined} className="analysis-contour" aside={aside}>
          {!source ? (
            <p className="muted small" data-testid="analysis-contour-note">
              {note}
            </p>
          ) : mode === "media" && !media ? (
            <p className="muted small" data-testid="analysis-contour-note">
              {NO_3D_TEXT}
            </p>
          ) : (
            body
          )}
        </Card>
      )}
    </ContourSlot>
  );
}
