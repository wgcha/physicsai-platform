import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api, type NotificationItem } from "../api";

/** 알림/대기열 항목 → 해당 작업의 Study 단계 화면으로 이동 */
export function useOpenJob() {
  const navigate = useNavigate();
  return useCallback(
    async (n: Pick<NotificationItem, "job_id" | "study_id" | "project_id">) => {
      if (!n.study_id || !n.project_id) return;
      let stage = 3;
      if (n.job_id) {
        try {
          stage = (await api.job(n.job_id)).stage;
        } catch {
          /* 기본 ③ */
        }
      }
      navigate(`/p/${n.project_id}/s/${n.study_id}/stage/${stage}`);
    },
    [navigate],
  );
}
