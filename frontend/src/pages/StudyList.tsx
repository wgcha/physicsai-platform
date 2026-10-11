import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, errorMessage, type Study } from "../api";
import { useApp, canExecuteIn } from "../app/AppContext";
import { fmtTime } from "../lib/format";
import { TopBar } from "../shell/TopBar";
import { CopyButton, Field, NO_PERMISSION_TIP } from "../components/ui";
import { StudyArchiveDialog } from "../components/StudyArchiveDialog";

const FOLDER_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

/** phase3.md §3.4 상태 필터(가정 A3-2: 기본 "사용 중"). 선택은 브라우저에 기억 */
type Filter = "ACTIVE" | "ARCHIVED" | "ALL";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "ACTIVE", label: "사용 중" },
  { key: "ARCHIVED", label: "보관" },
  { key: "ALL", label: "전체" },
];
const FILTER_KEY = "physicsai.studyList.filter";

function loadFilter(): Filter {
  try {
    const v = localStorage.getItem(FILTER_KEY);
    return v === "ARCHIVED" || v === "ALL" ? v : "ACTIVE";
  } catch {
    return "ACTIVE";
  }
}

function saveFilter(f: Filter) {
  try {
    localStorage.setItem(FILTER_KEY, f);
  } catch {
    /* 무시 */
  }
}

export function StudyList() {
  const { projectId = "" } = useParams();
  const { me, projects } = useApp();
  const navigate = useNavigate();
  const project = projects.find((p) => p.id === projectId);
  const canExec = canExecuteIn(me, projectId);
  const [studies, setStudies] = useState<Study[] | null>(null);
  const [filter, setFilterState] = useState<Filter>(loadFilter);
  const [archiving, setArchiving] = useState<Study | null>(null);
  const [reloadN, setReloadN] = useState(0);
  const [creating, setCreating] = useState(false);
  const [folder, setFolder] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setStudies(null);
    api
      .studies(projectId, filter === "ALL" ? undefined : filter)
      .then(setStudies)
      .catch((e) => setError(errorMessage(e)));
  }, [projectId, filter, reloadN]);

  const setFilter = (f: Filter) => {
    saveFilter(f);
    setFilterState(f);
  };

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
          <div className="seg" role="group" aria-label="상태 필터">
            {FILTERS.map((f) => (
              <button key={f.key} type="button" className={filter === f.key ? "on" : ""} aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
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
                <th>관리</th>
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
                  <td className="row-actions">
                    <Link to={`/p/${projectId}/s/${s.id}/manage`}>관리</Link>
                    {s.can_execute && s.status === "ACTIVE" && (
                      <button type="button" className="btn small ghost" onClick={() => setArchiving(s)}>
                        보관
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {archiving && (
          <StudyArchiveDialog
            study={archiving}
            onCancel={() => setArchiving(null)}
            onDone={() => {
              setArchiving(null);
              setReloadN((n) => n + 1);
            }}
          />
        )}
      </main>
    </div>
  );
}
