import { useEffect, useState } from "react";
import { api, errorMessage, type ParamSet, type TrainDoe } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute } from "../../hooks/useJobRunner";
import { Card } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { fmtTime } from "../../lib/format";
import { ParamSetDiscoverForm } from "./ParamSetDiscoverForm";
import { ResponseDefs } from "./ResponseDefs";
import { ContourDisplayForm } from "./ContourDisplayForm";
import { INPUT_KIND_LABEL, inputKindOf } from "./TemplatePicker";

type RegMode = "discover" | "folder" | "train";
const MODES: [RegMode, string][] = [
  ["discover", "프로젝트 폴더에서 찾기"],
  ["folder", "폴더 직접 지정"],
  ["train", "① 결과로 만들기"],
];

/** 템플릿 관리(phase3.md §13·§14.4·§14.6, S10): 고른 템플릿 요약·이름·입력 종류·응답 정의·컨투어 표시 + 새 템플릿 등록(관리자가 등록 · 사용자는 고르기만) */
export function ParamSetCard({ ps }: { ps: ParamSet | null }) {
  const { study, reloadParamSets } = useStudy();
  const canExec = useCanExecute();
  const [open, setOpen] = useState(!ps);
  const [mode, setMode] = useState<RegMode>("discover");
  const [label, setLabel] = useState("");
  const [path, setPath] = useState("");
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const done = async () => {
    await reloadParamSets();
    setOpen(false);
    setLabel("");
  };

  const register = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.registerParamSet(study.id, path.trim(), { label: label.trim() || null });
      await done();
      setPath("");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      title="템플릿 관리"
      span={9}
      className="paramset"
      aside={
        canExec ? (
          <button type="button" className="btn small ghost" onClick={() => setOpen((v) => !v)}>
            {open ? "닫기" : ps ? "새로 등록" : "등록"}
          </button>
        ) : (
          <span className="readonly small">조회 전용</span>
        )
      }
    >
      {ps ? (
        <div className="ps-summary">
          <ParamSetLabel key={ps.id} id={ps.id} label={ps.label ?? null} canEdit={canExec} onSaved={reloadParamSets} />
          <span>
            파라미터 <b>{ps.parameters.length}</b>
          </span>
          <span>
            학습 샘플 <b>{ps.sample_count}</b>
            {ps.sample_has_measured ? " (실측 포함)" : ""}
          </span>
          <span data-testid="ps-input-kind">
            입력 종류 <b>{INPUT_KIND_LABEL[inputKindOf(ps)]}</b>
          </span>
          <span>
            응답 <b>{ps.responses.length}</b>
          </span>
          <span>단위계 {ps.unit_system}</span>
          <span className="mono small muted ellipsis" title={ps.source_path}>
            {ps.origin === "TRAIN_DOE" ? `① 결과 · ${ps.source_path}` : ps.source_path}
          </span>
          <span className="small muted">
            {ps.registered_by_name} · {fmtTime(ps.registered_at)}
          </span>
        </div>
      ) : (
        <p className="muted">등록된 템플릿이 없습니다. 프로젝트 폴더를 지정하면 tpl·CAD·조립 폴더를 찾아 등록합니다.</p>
      )}
      {ps && !open && <ResponseDefs key={ps.id} ps={ps} canEdit={canExec} />}
      {ps && !open && <ContourDisplayForm key={`d-${ps.id}`} ps={ps} canEdit={canExec} />}
      {open && canExec && (
        <>
          <div className="seg ps-mode" role="group" aria-label="등록 방식">
            {MODES.map(([k, t]) => (
              <button key={k} type="button" className={mode === k ? "on" : ""} aria-pressed={mode === k} onClick={() => setMode(k)}>
                {t}
              </button>
            ))}
          </div>
          <label className="field">
            <span className="field-label">템플릿 이름(선택)</span>
            <input type="text" value={label} maxLength={120} placeholder="예: 쿠션 v1" aria-label="템플릿 이름" onChange={(e) => setLabel(e.target.value)} />
          </label>
        </>
      )}
      {open && canExec && mode === "discover" && <ParamSetDiscoverForm studyId={study.id} label={label} onDone={done} />}
      {open && canExec && mode === "train" && (
        <FromTrainForm label={label} onDone={done} />
      )}
      {open && canExec && mode === "folder" && (
        <div className="ps-register">
          <PathInput
            studyId={study.id}
            purpose="PARAM_SET"
            label="템플릿 폴더 경로"
            placeholder="E:/shared/AI_WORK/cushion/00_inbox/params"
            value={path}
            onChange={setPath}
            canExecute={canExec}
            onInspected={(r) => setOk(!!r?.ok)}
            renderSummary={(r) => (
              <div className="small">
                {Object.entries(r.summary)
                  .filter(([, v]) => typeof v !== "object")
                  .map(([k, v]) => (
                    <span key={k} className="kv">
                      {k} <b>{String(v)}</b>
                    </span>
                  ))}
              </div>
            )}
          />
          <div className="run-action-row">
            <button type="button" className="btn primary" disabled={!ok || busy} onClick={register}>
              {busy ? "등록 중…" : "등록"}
            </button>
            {error && <span className="error-text small" role="alert">{error}</span>}
          </div>
        </div>
      )}
    </Card>
  );
}

/** phase2.md §6.13·§14.4: ① DOE 결과로 파라미터 세트 만들기 */
function FromTrainForm({ label, onDone }: { label: string; onDone: () => Promise<void> }) {
  const { study } = useStudy();
  const [does, setDoes] = useState<TrainDoe[] | null>(null);
  const [doeId, setDoeId] = useState("");
  const [runs, setRuns] = useState<"collected" | "all">("collected");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .trainDoes(study.id)
      .then((l) => {
        const ready = l.filter((d) => d.status === "READY");
        setDoes(ready);
        setDoeId(ready[0]?.id ?? "");
      })
      .catch(() => setDoes([]));
  }, [study.id]);
  const doe = does?.find((d) => d.id === doeId);
  const noSamples = !!doe && doe.sample_status !== "PARSED" && doe.sample_status !== "PARTIAL";
  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.paramSetFromTrain(study.id, { doe_id: doeId, runs, label: label.trim() || null });
      await onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  if (does === null) return <div className="muted small">불러오는 중…</div>;
  if (!does.length) return <p className="muted small">준비된 ① DOE가 없습니다. ① 학습데이터 생성에서 먼저 만드세요.</p>;
  return (
    <div className="ps-register" data-testid="from-train">
      <div className="form-grid">
        <label className="field">
          <span className="field-label">DOE</span>
          <select value={doeId} onChange={(e) => setDoeId(e.target.value)} aria-label="DOE 선택">
            {does.map((d) => (
              <option key={d.id} value={d.id}>
                {d.doe_label} · 회수 {d.collected_count}/{d.run_count} · {fmtTime(d.created_at)}
              </option>
            ))}
          </select>
        </label>
        <div className="field">
          <span className="field-label">대상 run</span>
          <div className="seg" role="radiogroup" aria-label="대상 run">
            <button type="button" role="radio" aria-checked={runs === "collected"} className={runs === "collected" ? "on" : ""} onClick={() => setRuns("collected")}>
              회수된 run
            </button>
            <button type="button" role="radio" aria-checked={runs === "all"} className={runs === "all" ? "on" : ""} onClick={() => setRuns("all")}>
              전체
            </button>
          </div>
        </div>
      </div>
      {noSamples && <p className="muted small">이 DOE에는 샘플 표가 없어 만들 수 없습니다.</p>}
      <div className="run-action-row">
        <button type="button" className="btn primary" disabled={!doe || noSamples || busy} onClick={create}>
          {busy ? "만드는 중…" : "① 결과로 만들기"}
        </button>
        {error && <span className="error-text small" role="alert">{error}</span>}
      </div>
    </div>
  );
}

/** 세트 표시 이름(label) — "쿠션 v1"처럼 사용자가 알아볼 이름. 내용은 바뀌지 않는다(phase3 §13 S8) */
function ParamSetLabel({ id, label, canEdit, onSaved }: { id: string; label: string | null; canEdit: boolean; onSaved: () => Promise<void> }) {
  const [edit, setEdit] = useState(false);
  const [value, setValue] = useState(label ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setError(null);
    try {
      await api.patchParamSet(id, { label: value.trim() || null });
      await onSaved();
      setEdit(false);
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  if (edit)
    return (
      <span className="fill-row">
        <input type="text" value={value} maxLength={120} aria-label="새 이름" onChange={(e) => setValue(e.target.value)} />
        <button type="button" className="btn small" onClick={save}>
          저장
        </button>
        <button type="button" className="btn small ghost" onClick={() => setEdit(false)}>
          취소
        </button>
        {error && (
          <span className="error-text small" role="alert">
            {error}
          </span>
        )}
      </span>
    );
  return (
    <span data-testid="ps-label">
      <b>{label ?? "이름 없음"}</b>
      {canEdit && (
        <button type="button" className="btn small ghost" onClick={() => setEdit(true)}>
          이름 변경
        </button>
      )}
    </span>
  );
}
