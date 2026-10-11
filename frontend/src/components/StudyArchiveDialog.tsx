import { useState } from "react";
import { api, errorMessage, type Study } from "../api";
import { ConfirmDialog } from "./ConfirmDialog";

/** phase3.md §3.4: Study 보관·보관 해제 확인 대화상자(목록 행·관리 화면 공용). 409는 서버 문구 그대로. */
export function StudyArchiveDialog({
  study,
  onDone,
  onCancel,
}: {
  study: Pick<Study, "id" | "title" | "status">;
  onDone: (s: Study) => void;
  onCancel: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const archived = study.status === "ARCHIVED";
  const run = async () => {
    setError(null);
    try {
      onDone(await (archived ? api.unarchiveStudy(study.id) : api.archiveStudy(study.id)));
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  return archived ? (
    <ConfirmDialog
      title="보관 해제"
      body={`‘${study.title}’ Study를 다시 사용 중으로 바꿀까요? 작업을 다시 실행할 수 있게 됩니다.`}
      confirmLabel="보관 해제"
      onConfirm={run}
      onCancel={onCancel}
      error={error}
    />
  ) : (
    <ConfirmDialog
      title="Study 보관"
      body={`‘${study.title}’ Study를 보관할까요?\n보관하면 새 작업을 실행할 수 없습니다(조회와 용량 정리는 가능). 파일은 그대로 남고, 나중에 보관 해제할 수 있습니다.`}
      confirmLabel="보관"
      onConfirm={run}
      onCancel={onCancel}
      error={error}
    />
  );
}
