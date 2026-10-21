// 이 화면(번들)이 만들어진 소스 해시: scripts/build-frontend-dist가 VITE_BUILD_HASH로 넣는다(개발·시험·목 빌드에는 없음).
// 서버가 배치한 frontend 폴더의 해시(GET /version → build.source_hash)와 다르면 브라우저가 옛 화면을 들고 있는 것이다.
export function buildHash(): string | null {
  const h = import.meta.env.VITE_BUILD_HASH;
  return typeof h === "string" && h ? h : null;
}

export function isStaleBuild(mine: string | null, server: string | null | undefined): boolean {
  return !!mine && !!server && mine !== server;
}
