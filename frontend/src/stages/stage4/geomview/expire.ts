// 410 ARTIFACT_EXPIRED(서버측 임시 캐시 정리됨, geometry-view.md §6.6) → 같은 요청을 다시 보내 새로 만든다.
import { ApiError } from "../../../api";

export const isExpired = (e: unknown): boolean => e instanceof ApiError && (e.status === 410 || e.code === "ARTIFACT_EXPIRED");

/** load()가 410이면 reRequest() 후 다시 load(). 최대 max회 */
export async function withReRequest<T>(load: () => Promise<T>, reRequest: () => Promise<void>, max = 1): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await load();
    } catch (e) {
      if (!isExpired(e) || attempt >= max) throw e;
      await reRequest();
    }
  }
}

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
