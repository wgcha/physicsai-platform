import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { clearApiCache } from "../api";

if (!URL.createObjectURL) URL.createObjectURL = () => "blob:test";
if (!URL.revokeObjectURL) URL.revokeObjectURL = () => undefined;

afterEach(() => {
  cleanup();
  clearApiCache();
});
