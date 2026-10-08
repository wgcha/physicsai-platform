import { CurationProvider } from "./CurationContext";
import { SourcePicker, SpdmImportCard } from "./Sources";
import { H3dCurateCard, H3dPreviewCard, useH3dPreview } from "./H3dCards";
import { T01CurvesCard, T01PreviewCard, useT01Preview } from "./T01Cards";

function Stage2Cards() {
  const h3d = useH3dPreview();
  const t01 = useT01Preview();
  return (
    <div className="stage-grid stage2">
      <SourcePicker />
      <SpdmImportCard />
      <H3dPreviewCard shared={h3d} />
      <H3dCurateCard shared={h3d} />
      <T01PreviewCard shared={t01} />
      <T01CurvesCard shared={t01} />
    </div>
  );
}

/** ② 데이터 정리(phase2.md §14.3): 원천 선택 → ②-0 SPDM → ②-1/②-2 h3d → ②-3/②-4 T01 */
export function Stage2() {
  return (
    <CurationProvider>
      <Stage2Cards />
    </CurationProvider>
  );
}
