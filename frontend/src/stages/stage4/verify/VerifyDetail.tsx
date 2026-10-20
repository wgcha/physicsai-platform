// ④ FEM 검증 상세(phase3 §21.3.11): 머리(FV-003 · 상태 · 출처 링크) + 진행 4단(동반 예측이면 0단) + SCX 상태 + 취소·다시 실행,
// 탭 응답 | 커브 | 컨투어 | 입력·경로.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage, type Job } from "../../../api";
import { femVerifyApi, isFvActive, type FemVerification } from "../../../api/femVerify";
import { useStudy } from "../../../app/StudyContext";
import { ScxJobStatus, useScxMode } from "../../../components/HpcScx";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Card, CopyButton } from "../../../components/ui";
import { usePolling } from "../../../hooks/usePolling";
import { POLL } from "../../../lib/poll";
import { useCanExecute } from "../../../hooks/useJobRunner";
import { mdHm } from "../history/runListText";
import { ContourCompare } from "./ContourCompare";
import { ContourPanel } from "../geomview/contour/ContourPanel";
import { CurveCompare } from "./CurveCompare";
import { ResponseCompareTable } from "./ResponseCompareTable";
import { FV_STATE_TEXT, FV_STATUS_LABEL, fvStages, fvTone, pctText } from "./verifyRules";
import "../../../styles/femVerify.css";

type Tab = "responses" | "curves" | "contours" | "paths";
const TABS: { key: Tab; label: string }[] = [
  { key: "responses", label: "응답" },
  { key: "curves", label: "커브" },
  { key: "contours", label: "컨투어" },
  { key: "paths", label: "입력·경로" },
];

export function VerifyDetail({ fid }: { fid: string }) {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const scx = useScxMode();
  const base = `/p/${study.project_id}/s/${study.id}/stage`;
  const [fv, setFv] = useState<FemVerification | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("responses");
  const [confirm, setConfirm] = useState(false);

  const load = useCallback(async () => {
    try {
      const f = await femVerifyApi.get(fid);
      setFv(f);
      setError(null);
      setJob(f.job?.id ? await api.job(f.job.id).catch(() => null) : null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [fid]);
  useEffect(() => {
    setFv(null);
    setJob(null);
    void load();
  }, [load]);
  usePolling(load, fv && isFvActive(fv.status) ? POLL.batch : null, false, [fid]);

  if (error && !fv) return <Card span={9} title="FEM 검증"><p className="error-text">{error}</p><Link to={`${base}/4/verify`}>← FEM 검증 목록</Link></Card>;
  if (!fv) return <Card span={9} title="FEM 검증"><p className="muted">불러오는 중…</p></Card>;

  const act = async (f: () => Promise<unknown>) => {
    setActionError(null);
    try {
      await f();
      await load();
    } catch (e) {
      setActionError(errorMessage(e));
    }
  };
  const stages = fvStages(job, fv.predict.companion, fv.predict.state);
  const lk = fv.links;
  const ready = !!fv.compare;
  const showScx = (scx || fv.hpc_mode === "scx") && !!job;

  return (
    <>
      <Card span={9} title={`${fv.label} · ${fv.status_text}`} className="fv-head" aside={<Link className="small" to={`${base}/4/verify`}>← FEM 검증 목록</Link>}>
        <div className="run-action-row">
          <span className={`pill ${fvTone(fv.status)}`} data-testid="fv-status">{FV_STATUS_LABEL[fv.status]}</span>
          <span className="small" data-testid="fv-source-label">{fv.source.label}</span>
          {lk.predict_job_id && <Link className="small" to={`${base}/4?job=${lk.predict_job_id}`}>예측 결과</Link>}
          {lk.batch_id && <Link className="small" to={`${base}/4/batch/${lk.batch_id}`}>배치 행{lk.doe_no != null ? ` #${lk.doe_no}` : ""}</Link>}
          {lk.opt_id && <Link className="small" to={`${base}/5/surrogate/${lk.opt_id}`}>최적화</Link>}
          <span className="muted small">{mdHm(fv.created_at)} · {fv.created_by_name}</span>
          {fv.status === "DONE" && fv.max_abs_diff_pct != null && (
            <span className="small">최대 오차 <b>{pctText(fv.max_abs_diff_pct)}</b>{fv.worst ? <span className="muted"> ({fv.worst})</span> : null}</span>
          )}
        </div>
        <ol className="fv-stages" aria-label="진행 단계">
          {stages.map((s, i) => (
            <li key={s.key} className={`fv-stage ${s.state}`} data-testid={`fv-stage-${s.key}`}>
              <span className="no">{i + (stages[0].key === "predict" ? 0 : 1)}</span>
              <span>{s.label}</span>
              <span className="small">{FV_STATE_TEXT[s.state]}</span>
            </li>
          ))}
        </ol>
        {showScx && job && <ScxJobStatus job={job} canAct={canExec} />}
        {fv.failure && (
          <p className="error-text small" data-testid="fv-failure">
            {fv.failure.code} — {fv.failure.message}
          </p>
        )}
        <div className="run-action-row">
          {fv.can_cancel && (
            <button type="button" className="btn small danger" onClick={() => setConfirm(true)}>
              취소
            </button>
          )}
          {fv.can_rerun && (
            <button type="button" className="btn small primary" onClick={() => void act(() => femVerifyApi.rerun(fv.id))}>
              다시 실행
            </button>
          )}
          {actionError && <span className="error-text small" role="alert">{actionError}</span>}
        </div>
      </Card>

      <Card span={9} title="비교 결과" className="fv-tabs-card">
        <div className="tabs" role="tablist" aria-label="FEM 검증 결과">
          {TABS.map((t) => (
            <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} className={tab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
        {tab === "paths" ? (
          <PathsTab fv={fv} />
        ) : !ready ? (
          <p className="muted small" data-testid="fv-pending">
            {isFvActive(fv.status) ? "해석이 끝나면 응답·커브·컨투어 비교가 여기에 표시됩니다." : "비교 결과가 없습니다."}
          </p>
        ) : tab === "responses" ? (
          <ResponseCompareTable fid={fv.id} label={fv.label} compare={fv.compare!} warnings={fv.warnings} />
        ) : tab === "curves" ? (
          <CurveCompare fid={fv.id} curve={fv.compare!.curve} />
        ) : (
          <>
            <ContourCompare fid={fv.id} label={fv.label} legend={fv.compare!.legend} />
            <ContourPanel key={fv.id} source={{ source_kind: "SOLVER_H3D", source_ref: { fem_verification_id: fv.id } }} label="3D 컨투어(FEM 해석)" />
          </>
        )}
      </Card>

      {confirm && (
        <ConfirmDialog
          title={`${fv.label} 취소`}
          body={fv.status === "WAITING_PREDICT" ? "함께 실행 중인 예측을 취소합니다." : "진행 중인 FEM 검증 작업을 취소합니다. 이미 제출한 해석은 해석 시스템에서 따로 확인하세요."}
          confirmLabel="검증 취소"
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            setConfirm(false);
            void act(() => femVerifyApi.cancel(fv.id));
          }}
        />
      )}
    </>
  );
}

function PathsTab({ fv }: { fv: FemVerification }) {
  const rows: { key: string; label: string; value: string | null }[] = [
    { key: "dir", label: "검증 폴더", value: fv.dir },
    { key: "input_dir", label: "해석 입력(input)", value: fv.paths.input_dir },
    { key: "starter", label: "starter", value: fv.paths.starter },
    { key: "assembly", label: `조립 원본(${fv.assembly.label})`, value: fv.assembly.path },
    { key: "snapshot", label: "조립 스냅숏", value: fv.assembly.snapshot_dir },
    { key: "remote", label: "원격 폴더", value: fv.paths.remote_dir },
    { key: "result", label: "회수 결과(result)", value: fv.paths.result_dir },
  ];
  return (
    <div className="fv-section" data-testid="fv-paths">
      {rows
        .filter((r) => r.value)
        .map((r) => (
          <div key={r.key} className="codeline small" data-testid={`fv-path-${r.key}`}>
            <span className="field-label">{r.label}</span>
            <code>{r.value}</code>
            <CopyButton text={r.value!} label="경로 복사" />
          </div>
        ))}
      <p className="muted small">시도 {fv.attempt_no}회차 · {fv.input_mode === "rebuild" ? "메시 교체 후 조립" : "예측 입력 그대로"}</p>
    </div>
  );
}
