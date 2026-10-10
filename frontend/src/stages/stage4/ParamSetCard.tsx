import { useEffect, useState } from "react";
import { api, errorMessage, type TrainDoe } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute } from "../../hooks/useJobRunner";
import { Card } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { fmtTime } from "../../lib/format";

export function ParamSetCard() {
  const { study, currentParamSet: ps, reloadParamSets } = useStudy();
  const canExec = useCanExecute();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"folder" | "train">("folder");
  const [path, setPath] = useState("");
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const register = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.registerParamSet(study.id, path.trim());
      await reloadParamSets();
      setOpen(false);
      setPath("");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      title="파라미터 세트"
      className="wide paramset"
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
          <span>
            파라미터 <b>{ps.parameters.length}</b>
          </span>
          <span>
            학습 샘플 <b>{ps.sample_count}</b>
            {ps.sample_has_measured ? " (실측 포함)" : ""}
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
        <p className="muted">등록된 파라미터 세트가 없습니다. 파라미터 정의·학습 샘플·CAD·tpl·조립 파일이 든 폴더를 등록하세요.</p>
      )}
      {open && canExec && (
        <div className="seg ps-mode" role="group" aria-label="등록 방식">
          <button type="button" className={mode === "folder" ? "on" : ""} onClick={() => setMode("folder")}>
            폴더 등록
          </button>
          <button type="button" className={mode === "train" ? "on" : ""} onClick={() => setMode("train")}>
            ① 결과로 만들기
          </button>
        </div>
      )}
      {open && canExec && mode === "train" && (
        <FromTrainForm
          onDone={async () => {
            await reloadParamSets();
            setOpen(false);
          }}
        />
      )}
      {open && canExec && mode === "folder" && (
        <div className="ps-register">
          <PathInput
            studyId={study.id}
            purpose="PARAM_SET"
            label="파라미터 세트 폴더 경로"
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
function FromTrainForm({ onDone }: { onDone: () => Promise<void> }) {
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
      await api.paramSetFromTrain(study.id, { doe_id: doeId, runs });
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
