// 목: 플랫폼 버전·버전 게시판(GET만 — 작성·수정·삭제 경로 없음, 배포 RELEASES.md로만 기록).
import type { ReleasesResponse, VersionInfo } from "../api/types";
import { err, ok, type Route } from "./route";

export function mockReleases(): ReleasesResponse {
  return {
    current_version: "0.2.0",
    releases: [
      {
        version: "0.2.0",
        date: "2026-10-20",
        items: ["native 형상 엔진(자동 파라미터·모핑, NX·SimLab 독립)", "쉘 비드 모핑(chassis_rear)", "⑥ 최적화 HyperStudy 독립 — GA·NSGA-II"],
      },
      { version: "0.1.0", date: "2026-10-20", items: ["phase3 기준 운영 배포"] },
    ],
  };
}

export function mockVersion(r: ReleasesResponse): VersionInfo {
  return {
    platform_version: r.current_version,
    paicad_version: "0.10.0",
    build: { source_hash: "f".repeat(64), built_at: "2026-10-20T00:00:00Z" },
    git_commit: null,
  };
}

export const releaseRoutes: Route = (srv, c) => {
  if (c.path !== "/version" && c.path !== "/releases") return null;
  if (c.method !== "GET") return err(405, "METHOD_NOT_ALLOWED", "허용되지 않는 메서드입니다");
  if (srv.versionFails) return err(500, "INTERNAL_ERROR", "서버 내부 오류가 발생했습니다");
  return ok(c.path === "/version" ? mockVersion(srv.releases) : srv.releases);
};
