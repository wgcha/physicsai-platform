import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { clearApiCache } from "../api";

if (!URL.createObjectURL) URL.createObjectURL = () => "blob:test";
if (!URL.revokeObjectURL) URL.revokeObjectURL = () => undefined;

afterEach(() => {
  cleanup();
  clearApiCache();
});

// 내려받기(a.click())는 jsdom에서 탐색 미구현 경고만 내므로 무시
HTMLAnchorElement.prototype.click = function () {
  /* no-op */
};
