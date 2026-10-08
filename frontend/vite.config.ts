/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 계약 §4.2·§4.6: base /physicsai/, dev 127.0.0.1:5174, /physicsai/api → 백엔드 127.0.0.1:8100
export default defineConfig(({ mode }) => ({
  base: "/physicsai/",
  plugins: [react()],
  define: {
    __MOCK__: JSON.stringify(mode === "mock"),
  },
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    proxy:
      mode === "mock"
        ? undefined
        : { "/physicsai/api": { target: "http://127.0.0.1:8100", changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 600 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
}));
