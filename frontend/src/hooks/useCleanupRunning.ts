// phase3.md D3-24: Study 정리(STUDY_CLEANUP) 대기·실행 중이면 스캔 생성·Final 지정도 409 STUDY_CLEANUP_RUNNING.
// 화면은 GET /studies/{id}/storage의 active_cleanup_job_id로 미리 버튼을 막고, 409를 받으면 다시 조회한다.
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { usePolling } from "./usePolling";

export const CLEANUP_RUNNING_CODE = "STUDY_CLEANUP_RUNNING";
/** 버튼 옆·title 안내 */
export const CLEANUP_RUNNING_TEXT = "정리 진행 중";
export const CLEANUP_RUNNING_HINT = "Study 정리가 진행 중입니다. 정리가 끝난 뒤 다시 시도하세요";
/** 정리 진행 중 재조회 주기(시험에서 줄일 수 있도록 가변 객체) */
export const CLEANUP_POLL = { ms: 3000 };

export function isCleanupRunningError(e: unknown): boolean {
  return e instanceof ApiError && e.status === 409 && e.code === CLEANUP_RUNNING_CODE;
}

/** 409 STUDY_CLEANUP_RUNNING이면 동작별 한국어 문구, 아니면 null */
export function cleanupRunningMessage(e: unknown, action: string): string | null {
  return isCleanupRunningError(e) ? `Study 정리가 진행 중이라 ${action} 수 없습니다. 정리가 끝난 뒤 다시 시도하세요` : null;
}

/** 정리 진행 여부. 조회 실패는 버튼을 막지 않는다(서버 409가 최종 판정) */
export function useCleanupRunning(studyId: string) {
  const [running, setRunning] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const r = await api.studyStorage(studyId);
      setRunning(!!r.active_cleanup_job_id);
    } catch {
      /* 무시 */
    }
  }, [studyId]);
  useEffect(() => void refresh(), [refresh]);
  usePolling(refresh, running ? CLEANUP_POLL.ms : null, false, [studyId]);
  /** 409 STUDY_CLEANUP_RUNNING을 받았을 때: 즉시 진행 중으로 표시하고 다시 조회 */
  const onConflict = useCallback(
    (e: unknown) => {
      if (!isCleanupRunningError(e)) return false;
      setRunning(true);
      void refresh();
      return true;
    },
    [refresh],
  );
  return { running, refresh, onConflict };
}
