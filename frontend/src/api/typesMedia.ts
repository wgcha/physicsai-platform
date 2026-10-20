// API 타입(R-F 분할) — S10 컨투어 캡처(phase3.md §15). `api/types`가 재노출.
import type { S, Override } from "./typesBase";

// ---------------------------------------------------------------------------
// S10 컨투어 캡처(HyperView 방향별 PNG + 애니메이션 동영상, phase3.md §15) — 생성 타입 기반
// ---------------------------------------------------------------------------

/** 방향 키(기본 iso·front·top·right). 서버가 더 주면 그대로 표시 */
export type ViewKey = "iso" | "front" | "back" | "top" | "bottom" | "left" | "right" | (string & {});

/** PREDICT `result.media[]`(§15.2 — result는 dict라 생성 타입 없음) */
export interface ResultMedia {
  view: ViewKey;
  image_artifact_id: string;
  video_artifact_id: string | null;
}

/** 파일 1개(url = 표시용 Range 지원, download_url = 내려받기) */
// S16 V3(§21.4.5): playable·codec·transcoded·video_error — BE-V3 openapi 반영 전에도 같은 모양으로 읽는다
export type MediaFile = Omit<S["MediaFile"], "playable" | "codec" | "transcoded"> & { playable?: boolean | null; codec?: string | null; transcoded?: boolean };
export type MediaItem = Override<S["MediaItem"], { view: ViewKey; image: MediaFile; video?: MediaFile | null; video_error?: string | null }>;
/** NONE(캡처 전·step 없음) · SKIPPED(미구성) · OK · PARTIAL · FAILED */
export type MediaStatus = "NONE" | "SKIPPED" | "OK" | "PARTIAL" | "FAILED";
export type ContourLegend = S["CaptureLegendOut"];
/** 템플릿(파라미터 세트) 컨투어 표시 설정(PUT /param-sets/{id}/display 본문 `display`) */
export type ContourDisplay = Override<S["CaptureDisplayOut"], { views: ViewKey[] }>;
/** GET /jobs/{id}/media */
export type JobMedia = Override<S["JobMedia"], { status: MediaStatus; items: MediaItem[]; display?: ContourDisplay | null }>;
/** POST /jobs/{id}/capture 본문(→ 201 Job CONTOUR_RECAPTURE) */
export type CaptureRequest = S["RecaptureRequest"];
