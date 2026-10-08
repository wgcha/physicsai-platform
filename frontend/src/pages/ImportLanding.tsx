import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, errorMessage, type PathInspectResult, type Study } from "../api";
import { canExecuteIn, useApp } from "../app/AppContext";
import { TopBar } from "../shell/TopBar";
import { CodeLine, Field, NO_PERMISSION_TIP } from "../components/ui";
import { useFeature, featureText } from "../components/FeatureGate";
import { SpdmSummary } from "../stages/stage2/Sources";

/**
 * phase2.md §12.7 딥링크: /physicsai/import?spdm_path=…[&project_id=…]
 * 링크를 여는 것만으로는 작업을 만들지 않는다. Study를 고르고 "가져오기"를 눌러야 한다.
 */
export function ImportLanding() {
  const { me, projects } = useApp();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const spdmPath = params.get("spdm_path") ?? "";
  const feature = useFeature("spdm_import");
  const [projectId, setProjectId] = useState(params.get("project_id") ?? "");
  const [studies, setStudies] = useState<Study[]>([]);
  const [studyId, setStudyId] = useState("");
  const [creating, setCreating] = useState(false);
  const [newStudy, setNewStudy] = useState({ folder_name: "", title: "" });
  const [inspect, setInspect] = useState<PathInspectResult | null>(null);
  const [inspectError, setInspectError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId && projects[0]) setProjectId(projects[0].id);
  }, [projectId, projects]);

  useEffect(() => {
    setStudies([]);
    setStudyId("");
    if (!projectId) return;
    let alive = true;
    api
      .studies(projectId, "ACTIVE")
      .then((l) => {
        if (!alive) return;
        setStudies(l);
        setStudyId(l[0]?.id ?? "");
      })
      .catch(() => alive && setStudies([]));
    return () => {
      alive = false;
    };
  }, [projectId]);

  // Study가 정해지면 경로 확인(읽기만, 작업 생성 없음)
  useEffect(() => {
    setInspect(null);
    setInspectError(null);
    if (!studyId || !spdmPath || !feature.enabled) return;
    let alive = true;
    api
      .inspectPath(studyId, "SPDM_IMPORT", spdmPath)
      .then((r) => alive && setInspect(r))
      .catch((e) => alive && setInspectError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [studyId, spdmPath, feature.enabled]);

  const canExec = canExecuteIn(me, projectId);

  const createStudy = async () => {
    setBusy(true);
    setError(null);
    try {
      const s = await api.createStudy({ project_id: projectId, folder_name: newStudy.folder_name.trim(), title: newStudy.title.trim() || newStudy.folder_name.trim() });
      setStudies((l) => [s, ...l]);
      setStudyId(s.id);
      setCreating(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const doImport = async () => {
    setBusy(true);
    setError(null);
    try {
      const job = await api.createJob(studyId, "SPDM_IMPORT", { spdm_path: spdmPath });
      navigate(`/p/${projectId}/s/${studyId}/stage/2?import_job=${encodeURIComponent(job.id)}`);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <TopBar crumbs={[{ label: "SPDM 가져오기" }]} projectId={projectId || undefined} />
      <main className="page-main narrow">
        <h1 className="page-title">SPDM 결과를 AI 학습 데이터로 가져오기</h1>
        {!spdmPath ? (
          <div className="empty">SPDM 경로가 없습니다. 대시보드의 링크로 다시 들어오세요.</div>
        ) : (
          <section className="card" aria-label="SPDM 가져오기">
            <div className="card-body">
              <div>
                <div className="field-label">SPDM 경로 (읽기 전용)</div>
                <CodeLine text={spdmPath} />
              </div>
              {!feature.enabled && <p className="muted small feature-off" data-testid="feature-off-spdm_import">{featureText(feature)}</p>}
              <div className="form-grid">
                <Field label="프로젝트">
                  <select value={projectId} onChange={(e) => setProjectId(e.target.value)} aria-label="프로젝트">
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Study">
                  <select value={studyId} onChange={(e) => setStudyId(e.target.value)} aria-label="Study" disabled={!studies.length}>
                    {studies.length === 0 && <option value="">Study 없음</option>}
                    {studies.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.title} ({s.folder_name})
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              {canExec && (
                <div>
                  {creating ? (
                    <div className="form-grid">
                      <Field label="폴더 이름" hint="영문·숫자·_- (64자)">
                        <input className="mono" value={newStudy.folder_name} onChange={(e) => setNewStudy({ ...newStudy, folder_name: e.target.value })} aria-label="폴더 이름" />
                      </Field>
                      <Field label="제목">
                        <input value={newStudy.title} onChange={(e) => setNewStudy({ ...newStudy, title: e.target.value })} aria-label="제목" />
                      </Field>
                      <div className="run-action-row">
                        <button type="button" className="btn" onClick={() => void createStudy()} disabled={busy || !newStudy.folder_name.trim()}>
                          Study 만들기
                        </button>
                        <button type="button" className="btn ghost" onClick={() => setCreating(false)}>
                          닫기
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button type="button" className="btn small ghost" onClick={() => setCreating(true)}>
                      새 Study
                    </button>
                  )}
                </div>
              )}
              {inspect && (
                <div className={inspect.ok ? "inspect ok" : "inspect bad"} data-testid="import-inspect">
                  <SpdmSummary s={inspect.summary} />
                  {inspect.problems.map((p, i) => (
                    <div key={i} className="small">
                      <code>{p.code}</code> {p.message}
                    </div>
                  ))}
                </div>
              )}
              {inspectError && <div className="error-text small" role="alert">{inspectError}</div>}
              <div className="run-action-row">
                {canExec ? (
                  <button type="button" className="btn primary" onClick={() => void doImport()} disabled={busy || !feature.enabled || !studyId || !inspect?.ok}>
                    가져오기
                  </button>
                ) : (
                  <span className="readonly" title={NO_PERMISSION_TIP}>
                    조회 전용 <span className="muted small">· {NO_PERMISSION_TIP}</span>
                  </span>
                )}
                {error && <span className="error-text small" role="alert">{error}</span>}
              </div>
              <p className="muted small">가져오기를 누르면 이 Study의 ② 데이터 정리로 이동하고, 원천에 이 가져오기가 선택됩니다.</p>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
