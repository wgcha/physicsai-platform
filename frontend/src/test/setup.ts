import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { clearApiCache } from "../api";

if (!URL.createObjectURL) URL.createObjectURL = () => "blob:test";
if (!URL.revokeObjectURL) URL.revokeObjectURL = () => undefined;

afterEach(() => {
  cleanup();
  clearApiCache();
});

// jsdom은 canvas.getContext가 미구현(호출마다 "Not implemented" 오류 로그) — 기본은 null(WebGL 없음)로 조용히 대체. 3D 시험은 spyOn으로 켠다
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext;

// 내려받기(a.click())는 jsdom에서 탐색 미구현 경고만 내므로 무시
HTMLAnchorElement.prototype.click = function () {
  /* no-op */
};
