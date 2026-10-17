// 테마 동기화(2026-10-17 사용자 결정): 대시보드(simdashboard)와 같은 origin이므로 대시보드가 저장한 테마를 그대로 따른다.
// 대시보드 원본: frontend/src/app/preferences/workspacePreferences.ts — 키 'simdashboard.workspace.theme.v1'(값 'dark'|'light'),
// 레거시 키 'vd-workbench-theme', 기본 'dark'. PhysicsAI는 읽기만 한다(자체 토글 없음, 저장하지 않음).
import { useEffect, useState } from "react";

export type Theme = "dark" | "light";

export const THEME_KEY = "simdashboard.workspace.theme.v1";
export const LEGACY_THEME_KEY = "vd-workbench-theme";
export const DEFAULT_THEME: Theme = "dark";

type StorageLike = Pick<Storage, "getItem">;

function valid(v: string | null | undefined): Theme | undefined {
  return v === "dark" || v === "light" ? v : undefined;
}

function read(storage: StorageLike | undefined, key: string): string | null {
  try {
    return storage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function defaultStorage(): StorageLike | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

/** 새 키 → 레거시 키 → 'dark'. 저장소 접근이 실패하면 'dark' */
export function readTheme(storage: StorageLike | undefined = defaultStorage()): Theme {
  return valid(read(storage, THEME_KEY)) ?? valid(read(storage, LEGACY_THEME_KEY)) ?? DEFAULT_THEME;
}

export function applyTheme(theme: Theme, root: HTMLElement = document.documentElement): void {
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}

/** 시작 시 1회 적용 + 다른 탭(대시보드)에서 바꾸면 storage 이벤트로 따라간다 */
export function useThemeSync(): void {
  useEffect(() => {
    applyTheme(readTheme());
    const onStorage = (e: StorageEvent) => {
      if (e.key === null || e.key === THEME_KEY || e.key === LEGACY_THEME_KEY) applyTheme(readTheme());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
}

/** 현재 <html data-theme> 값(바뀌면 다시 그린다 — 캔버스 차트 색 갱신용) */
export function useCurrentTheme(): Theme {
  const [theme, setTheme] = useState<Theme>(() => valid(document.documentElement.dataset.theme) ?? DEFAULT_THEME);
  useEffect(() => {
    const root = document.documentElement;
    const mo = new MutationObserver(() => setTheme(valid(root.dataset.theme) ?? DEFAULT_THEME));
    mo.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);
  return theme;
}
