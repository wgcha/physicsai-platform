import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, errorMessage, type Study } from "../api";
import { useApp, canExecuteIn } from "../app/AppContext";
import { fmtTime } from "../lib/format";
import { TopBar } from "../shell/TopBar";
import { CopyButton, Field, NO_PERMISSION_TIP } from "../components/ui";

const FOLDER_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

export function StudyList() {
  const { projectId = "" } = useParams();
  const { me, projects } = useApp();
  const navigate = useNavigate();
  const project = projects.find((p) => p.id === projectId);
  const canExec = canExecuteIn(me, projectId);
  const [studies, setStudies] = useState<Study[] | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const [folder, setFolder] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setStudies(null);
    api
      .studies(projectId, showArchived ? undefined : "ACTIVE")
      .then(setStudies)
      .catch((e) => setError(errorMessage(e)));
  }, [projectId, showArchived]);

  const folderOk = FOLDER_RE.test(folder);
  const create = async () => {
    setError(null);
    try {
      const s = await api.createStudy({ project_id: projectId, folder_name: folder, title: title.trim() });
      navigate(`/p/${projectId}/s/${s.id}/stage/3`);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <div className="page">
      <TopBar crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }]} projectId={projectId} />
      <main className="page-main narrow">
        <div className="page-title-row">
          <h1 className="page-title">Study</h1>
          <label className="check small">
            <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> 보관된 Study 포함
          </label>
          <span className="spacer" />
          {canExec ? (
            <button type="button" className="btn primary" onClick={() => setCreating((v) => !v)}>
              새 Study
            </button>
          ) : (
            <span className="readonly" title={NO_PERMISSION_TIP}>
              조회 전용
            </span>
          )}
        </div>
        {creating && canExec && (
          <div className="card create-form" aria-label="새 Study">
            <div className="form-grid">
              <Field label="폴더 이름" hint="영문·숫자·_·- 64자 이내, 생성 후 변경 불가. AI 루트 아래에 같은 이름 폴더가 생깁니다.">
                <input className="mono" value={folder} onChange={(e) => setFolder(e.target.value)} aria-invalid={!!folder && !folderOk} />
              </Field>
              <Field label="제목">
                <input value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} />
              </Field>
            </div>
            <div className="run-action-row">
              <button type="button" className="btn primary" disabled={!folderOk || !title.trim()} onClick={create}>
                만들기
              </button>
              <button type="button" className="btn ghost" onClick={() => setCreating(false)}>
                닫기
              </button>
            </div>
          </div>
        )}
        {error && <div className="error-text" role="alert">{error}</div>}
        {studies === null ? (
          <div className="empty">불러오는 중…</div>
        ) : studies.length === 0 ? (
          <div className="empty">Study가 없습니다</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>제목</th>
                <th>폴더</th>
                <th>상태</th>
                <th>만든 사람</th>
                <th>수정</th>
              </tr>
            </thead>
            <tbody>
              {studies.map((s) => (
                <tr key={s.id}>
                  <td>
                    <Link to={`/p/${projectId}/s/${s.id}/stage/3`}>{s.title}</Link>
                  </td>
                  <td className="mono" title={s.folder_display_path ?? undefined}>
                    {s.folder_name}
                    {s.folder_display_path && <CopyButton text={s.folder_display_path} label="경로 복사" />}
                  </td>
                  <td>{s.status === "ACTIVE" ? "사용 중" : "보관"}</td>
                  <td>{s.created_by_name}</td>
                  <td className="num">{fmtTime(s.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>
    </div>
  );
}
