// API 타입(doe-preview.md §6.6) — DOE 표본 형상 그리드 미리보기. 생성 스키마(schema.d.ts)의 DoePreview*를 그대로 쓰고,
// 화면이 좁혀 읽는 곳만 덮어쓴다(응답 필드 이름은 백엔드 실제와 같다: png/glb/manifest_artifact_id, gen{status,code,step}, top_changes, clipped).
import type { Override, S } from "./typesBase";

export type DoePreviewSourceKind = S["DoePreviewSource"]["kind"];
export type DoePreviewOrder = S["DoePreviewSelect"]["order"];
export type DoePreviewStatus = S["DoePreview"]["status"];
export type DoePreviewCellStatus = S["DoePreviewCell"]["status"];

export type DoePreviewSource = S["DoePreviewSource"];
/** 요청의 `select`는 화면이 항상 offset·limit을 보낸다(offset 0 = 공칭 + limit−1, 이후 = 지금까지 보인 셀 수) */
export type DoePreviewSelect = Override<S["DoePreviewSelect"], { limit: number; desc?: boolean }>;
/** POST /studies/{id}/doe-previews 본문. sampling = TD_DOE_GEN native params의 sampling과 같은 모양(train_doe면 생략) */
export type DoePreviewReq = Override<S["DoePreviewReq"], { select: DoePreviewSelect; sampling?: Record<string, unknown> | null }>;
export type DoePreviewTopChange = S["DoePreviewTopChange"];
/** train_doe만: 생성 후 결과(SKIPPED 코드·단계) */
export type DoePreviewGen = S["DoePreviewGen"];
/** 응답은 기본값 필드(nominal·clipped)를 항상 싣는다 — 화면 mock은 생략해도 되게 선택으로 둔다 */
export type DoePreviewCell = Override<S["DoePreviewCell"], { nominal?: boolean; clipped?: boolean }>;
/** `cells`는 항상 배열(기본 []), `disp_range_mm`은 [하한, 상한] 2개(생성 스키마는 number[]) */
export type DoePreview = Override<S["DoePreview"], { cells: DoePreviewCell[]; disp_range_mm?: [number, number] | null }>;
