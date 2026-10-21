// 브라우저 분할 업로드 API(upload-report.md §4) — 타입(생성 스키마 별칭) + 요청 함수. 모든 쓰기는 X-PhysicsAI-Request 헤더(client.request).
import { putBinary, request } from "./client";
import type { components } from "./generated/schema";
import type { PathInspectResult, PathPurpose } from "./types";

type S = components["schemas"];

/** 업로드 purpose = paths/inspect purpose(SPDM_IMPORT 제외) + 업로드 전용 DISCOVER(inspect 없음) */
export type UploadPurpose = Exclude<PathPurpose, "SPDM_IMPORT" | "FEM_ASSEMBLY"> | "DISCOVER";
export type UploadConfig = S["UploadConfig"];
export type UploadPurposeInfo = S["UploadPurposeInfo"];
export type UploadItemIn = S["UploadItemIn"];
export type UploadEntry = S["UploadEntryOut"];
export type UploadChunkOut = S["UploadChunkOut"];
export type UploadCreate = Omit<S["UploadCreate"], "purpose"> & { purpose: UploadPurpose };
export type Upload = Omit<S["UploadOut"], "inspect"> & { inspect?: PathInspectResult | null };
export type UploadComplete = Omit<S["UploadCompleteOut"], "inspect"> & { inspect?: PathInspectResult | null };

export const uploadApi = {
  config: () => request<UploadConfig>("GET", "/uploads/config"),
  create: (studyId: string, body: UploadCreate) => request<Upload>("POST", `/studies/${studyId}/uploads`, { body }),
  get: (id: string) => request<Upload>("GET", `/uploads/${encodeURIComponent(id)}`),
  addFiles: (id: string, files: UploadItemIn[]) => request<Upload>("POST", `/uploads/${encodeURIComponent(id)}/files`, { body: { files } }),
  /** 청크 PUT: offset = 서버 received 와 같아야 한다(어긋나면 409 UPLOAD_OFFSET_MISMATCH + received). sha256 = 청크 검사값(선택) */
  putChunk: (id: string, index: number, offset: number, blob: Blob, sha256?: string | null) =>
    putBinary<UploadChunkOut>(`/uploads/${encodeURIComponent(id)}/files/${index}`, { offset }, blob, sha256 ? { "X-Chunk-Sha256": sha256 } : {}),
  complete: (id: string) => request<UploadComplete>("POST", `/uploads/${encodeURIComponent(id)}/complete`),
  /** OPEN만 — 받은 것은 서버가 _backup 으로 옮긴다(COMPLETED 는 409 UPLOAD_CLOSED) */
  cancel: (id: string) => request<void>("DELETE", `/uploads/${encodeURIComponent(id)}`),
};
