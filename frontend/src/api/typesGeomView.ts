// API 타입(geometry-view.md §6.5·§6.9·§13.5) — 형상 3D 뷰·미리보기·결과 3D 컨투어. `api/types`가 재노출.
import type { Override, S } from "./typesBase";

/** 공칭 3D 뷰(④ `GET /param-sets/{id}/view`, ① `GET /studies/{id}/train/view`) */
export type GeomView = S["GeomView"];
export type GeomPreviewStatus = S["GeomPreview"]["status"];
/** 미리보기 1건(`POST /param-sets/{id}/previews` 200 캐시 적중 | 202, `GET /previews/{id}`) */
export type GeomPreview = S["GeomPreview"];
export type GeomPreviewCreate = { values: Record<string, number>; fe?: "off" | "check" };

export type Contour3dSourceKind = S["Contour3dCreate"]["source_kind"];
export type Contour3dCreate = Override<S["Contour3dCreate"], { display?: S["Contour3dDisplay"] | null }>;
export type Contour3dProgress = S["Contour3dProgress"];
export type Contour3dPhase = Contour3dProgress["phase"];
/** 결과 3D 컨투어(`POST /contour3d` 200|202, `GET /contour3d/{id}`, `POST /contour3d/{id}/cancel`) */
export type Contour3d = S["Contour3d"];
