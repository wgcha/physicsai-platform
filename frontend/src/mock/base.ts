// 목 기초 값: 난수·시각·사용자·프로젝트(data.ts가 재노출).
import type { Me, Project } from "../api/types";

export function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export type MockUserKey = "admin" | "power" | "general" | "anon";

export const USERS: Record<Exclude<MockUserKey, "anon">, Me> = {
  admin: { user_id: "u-admin", username: "admin01", display_name: "박관리", is_global_admin: true, roles: {} },
  power: { user_id: "u-power", username: "kim.res", display_name: "김연구", is_global_admin: false, roles: { "p-cushion": "power", "p-hinge": "general" } },
  general: { user_id: "u-general", username: "lee.view", display_name: "이조회", is_global_admin: false, roles: { "p-cushion": "general" } },
};

export const PROJECTS: Project[] = [
  { id: "p-cushion", name: "폴더블 쿠션 구조", product_name: "FD-X 2027" },
  { id: "p-hinge", name: "힌지 내구 해석", product_name: "FD-X 2027" },
  { id: "p-battery", name: "배터리 낙하 충격", product_name: "BR-S" },
];

export const T0 = Date.parse("2026-10-08T09:00:00+09:00");
export const iso = (minAgo: number, base = Date.now()) => new Date(base - minAgo * 60_000).toISOString();
