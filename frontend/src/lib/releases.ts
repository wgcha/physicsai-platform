// 버전 게시판 보조: 마지막으로 본 버전(localStorage — 실패해도 동작)과 버전 비교. 기록은 배포(RELEASES.md)로만 한다.
export const LAST_SEEN_KEY = "physicsai.lastSeenVersion";
/** 같은 창에서 본 버전이 바뀌면 배지를 다시 그리게 알리는 이벤트 */
export const LAST_SEEN_EVENT = "physicsai:last-seen-version";

export function readLastSeen(): string | null {
  try {
    return window.localStorage.getItem(LAST_SEEN_KEY);
  } catch {
    return null;
  }
}

export function writeLastSeen(v: string): void {
  try {
    window.localStorage.setItem(LAST_SEEN_KEY, v);
  } catch {
    /* 저장 불가(사생활 모드 등) — 표시만 매번 '새 버전' */
  }
  window.dispatchEvent(new Event(LAST_SEEN_EVENT));
}

/** x.y.z 비교: a > b면 양수. 숫자가 아닌 부분은 0 */
export function compareVersion(a: string, b: string): number {
  const pa = a.split(".").map((x) => Number.parseInt(x, 10) || 0);
  const pb = b.split(".").map((x) => Number.parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d) return d;
  }
  return 0;
}

/** 마지막으로 본 버전보다 새 버전인가(본 기록이 없으면 새 버전) */
export function isNewVersion(version: string, lastSeen: string | null): boolean {
  return lastSeen === null || compareVersion(version, lastSeen) > 0;
}
