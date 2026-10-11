import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, errorMessage, type Study } from "../api";
import { useApp } from "../app/AppContext";
import { fmtTime } from "../lib/format";
import { TopBar } from "../shell/TopBar";
import { Card, CodeLine, Field, NO_PERMISSION_TIP } from "../components/ui";
import { StudyArchiveDialog } from "../components/StudyArchiveDialog";

const CONFLICT_TEXT = "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요";

function ReadOnly() {
  return (
    <span className="readonly" title={NO_PERMISSION_TIP}>
      조회 전용 <span className="muted small">· {NO_PERMISSION_TIP}</span>
    </span>
  );
}

/** phase3.md §3.4 Study 관리 화면: ① 기본 정보(이름 변경) ② 보관 (③ 용량·정리는 S3) */
export function StudyManage() {
  const { projectId = "", studyId = "" } = useParams();
  const { projects } = useApp();
  const project = projects.find((p) => p.id === projectId);
  const [study, setStudy] = useState<Study | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setStudy(await api.study(studyId));
    } catch (e) {
      setLoadError(errorMessage(e));
    }
  }, [studyId]);

  useEffect(() => {
    setStudy(null);
    setLoadError(null);
    void reload();
  }, [reload]);

  const base = `/p/${projectId}/s/${studyId}`;
  return (
    <div className="page">
      <TopBar
        projectId={projectId}
        crumbs={[
          { label: project?.name ?? projectId, to: `/p/${projectId}` },
          { label: study?.title ?? studyId, to: `${base}/stage/3` },
          { label: "Study 관리" },
        ]}
      />
      <main className="page-main narrow manage-page">
        <div className="page-title-row">
          <h1 className="page-title">Study 관리</h1>
          <span className="spacer" />
          <Link to={`${base}/stage/3`}>작업 화면으로</Link>
        </div>
        {loadError ? (
          <div className="error-text" role="alert">
            Study를 불러오지 못했습니다: {loadError}
          </div>
        ) : !study ? (
          <div className="empty">불러오는 중…</div>
        ) : (
          <>
            <InfoSection study={study} onSaved={setStudy} reload={reload} />
            <ArchiveSection study={study} onChanged={setStudy} />
          </>
        )}
      </main>
    </div>
  );
}

function InfoSection({ study, onSaved, reload }: { study: Study; onSaved: (s: Study) => void; reload: () => Promise<void> }) {
  const [title, setTitle] = useState(study.title);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => setTitle(study.title), [study.title, study.version]);

  const trimmed = title.trim();
  const valid = trimmed.length >= 1 && trimmed.length <= 120;
  const save = async () => {
    setError(null);
    setSaved(false);
    setSaving(true);
    try {
      onSaved(await api.patchStudy(study.id, { version: study.version, title: trimmed }));
      setSaved(true);
    } catch (e) {
      if (e instanceof ApiError && e.code === "VERSION_CONFLICT") {
        setError(CONFLICT_TEXT);
        await reload();
      } else setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card step="①" title="기본 정보">
      {study.can_execute ? (
        <div className="manage-rename">
          <Field label="표시 이름" hint={`폴더 이름 ${study.folder_name}은 바뀌지 않습니다(표시 이름만 변경)`}>
            <input
              value={title}
              maxLength={120}
              onChange={(e) => {
                setTitle(e.target.value);
                setSaved(false);
              }}
              aria-invalid={!valid}
            />
          </Field>
          <div className="run-action-row">
            <button type="button" className="btn primary" disabled={!valid || saving || trimmed === study.title} onClick={save}>
              저장
            </button>
            {saved && <span className="muted small">저장했습니다</span>}
          </div>
        </div>
      ) : (
        <div className="manage-rename">
          <div>
            <span className="muted small">표시 이름</span> {study.title}
          </div>
          <ReadOnly />
        </div>
      )}
      {error && (
        <div className="error-text small" role="alert">
          {error}
        </div>
      )}
      <dl className="kv">
        <dt>폴더</dt>
        <dd>{study.folder_display_path ? <CodeLine text={study.folder_display_path} /> : <span className="mono">{study.folder_name}</span>}</dd>
        <dt>상태</dt>
        <dd data-testid="study-status">{study.status === "ACTIVE" ? "사용 중" : "보관"}</dd>
        <dt>만든 사람</dt>
        <dd>
          {study.created_by_name} · {fmtTime(study.created_at)}
        </dd>
      </dl>
    </Card>
  );
}

function ArchiveSection({ study, onChanged }: { study: Study; onChanged: (s: Study) => void }) {
  const [open, setOpen] = useState(false);
  const archived = study.status === "ARCHIVED";
  return (
    <Card step="②" title="보관">
      <p className="muted small">
        {archived
          ? "보관된 Study입니다. 조회와 용량 정리만 할 수 있고 새 작업은 실행할 수 없습니다."
          : "보관하면 새 작업을 실행할 수 없습니다. 파일은 그대로 남고 언제든 보관 해제할 수 있습니다."}
      </p>
      {study.can_execute ? (
        <button type="button" className="btn" onClick={() => setOpen(true)}>
          {archived ? "보관 해제" : "보관"}
        </button>
      ) : (
        <ReadOnly />
      )}
      {open && (
        <StudyArchiveDialog
          study={study}
          onCancel={() => setOpen(false)}
          onDone={(s) => {
            setOpen(false);
            onChanged(s);
          }}
        />
      )}
    </Card>
  );
}
