import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import "./styles.css";
import { applyTheme, readTheme } from "./design/theme";

// 대시보드 테마를 첫 렌더 전에 적용(깜박임 방지). 이후 변경은 App의 useThemeSync가 따라간다.
applyTheme(readTheme());

async function start() {
  if (__MOCK__) {
    // 백엔드 없이 동작하는 개발 모드(npm run dev:mock). 운영 빌드에서는 import되지 않는다.
    const { installMockFetch } = await import("./mock/install");
    installMockFetch();
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void start();
