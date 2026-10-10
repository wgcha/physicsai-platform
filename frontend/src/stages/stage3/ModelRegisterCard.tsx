import { useState } from "react";
import { type Model } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, CopyButton, Field, RunAction } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { fmtTime } from "../../lib/format";

const NAME_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;

export function LogStatusText({ m }: { m: Pick<Model, "log_status" | "log_parser"> }) {
  if (m.log_status === "PARSED") return <span className="small">파싱됨{m.log_parser ? ` (${m.log_parser})` : ""}</span>;
  if (m.log_status === "UNRECOGNIZED") return <span className="muted small">로그 형식 미확인</span>;
  return <span className="muted small">로그 없음</span>;
}

export function ModelRegisterCard() {
  const { study, datasets, models, reloadModels } = useStudy();
  const canExec = useCanExecute();
  const [path, setPath] = useState("");
  const [logs, setLogs] = useState<string[]>([]);
  const [ok, setOk] = useState(false);
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [dsId, setDsId] = useState("");
  const [logFile, setLogFile] = useState("");
  const { job, run, error } = useJobRunner("MODEL_REGISTER", () => void reloadModels());
  // 최신 등록 작업의 결과 모델(로그 상태 표시)
  const registeredId = job?.state === "SUCCEEDED" ? (job.result as { model_id?: string } | null)?.model_id : undefined;
  const registered = registeredId ? models.find((x) => x.id === registeredId) ?? null : null;

  const readyDs = datasets.filter((d) => d.status === "READY");
  const nameOk = NAME_RE.test(name);
  const needLogChoice = logs.length > 1 && !logFile;

  const submit = () =>
    void run({
      model_path: path.trim(),
      name,
      label: label.trim() || null,
      dataset_id: dsId || null,
      log_file: logFile || null,
    });

  return (
    <Card step="③-4" title="모델 등록">
      <PathInput
        studyId={study.id}
        purpose="MODEL_FOLDER"
        label="모델 폴더 경로 (.psmdl·.pscfg·로그)"
        placeholder="E:/shared/AI_WORK/cushion/00_inbox/model_v3"
        value={path}
        onChange={setPath}
        canExecute={canExec}
        onInspected={(r) => {
          setOk(!!r?.ok);
          const l = r?.summary.logs ?? [];
          setLogs(l);
          setLogFile(l.length === 1 ? l[0] : "");
          const stem = r?.summary.psmdl?.[0]?.replace(/\.psmdl$/i, "");
          if (stem && !name) setName(stem);
        }}
        renderSummary={(r) => (
          <div className="summary-grid small">
            <span>psmdl</span>
            <span className="mono">{r.summary.psmdl?.join(", ") || "없음"}</span>
            <span>pscfg</span>
            <span className="mono">{r.summary.pscfg?.join(", ") || "없음"}</span>
            <span>로그</span>
            <span className="mono">{r.summary.logs?.join(", ") || "없음 (등록은 가능)"}</span>
          </div>
        )}
      />
      <div className="form-grid">
        <Field label="모델 이름" hint={name && !nameOk ? "영문으로 시작, 영문·숫자·_ 64자 이내" : "같은 이름이면 버전이 올라갑니다"}>
          <input className="mono" value={name} onChange={(e) => setName(e.target.value)} disabled={!canExec} aria-invalid={!!name && !nameOk} />
        </Field>
        {logs.length > 1 && (
          <Field label="학습 로그 파일" hint="로그 후보가 여러 개입니다. 하나를 고르세요">
            <select value={logFile} onChange={(e) => setLogFile(e.target.value)}>
              <option value="">선택…</option>
              {logs.map((l) => (
                <option key={l}>{l}</option>
              ))}
            </select>
          </Field>
        )}
      </div>
      <Advanced>
        <div className="form-grid">
          <Field label="표시명">
            <input value={label} maxLength={120} onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <Field label="학습 데이터셋" hint="평가는 이 데이터셋의 평가용(홀드아웃)으로 합니다">
            <select value={dsId} onChange={(e) => setDsId(e.target.value)}>
              <option value="">최신 준비된 데이터셋</option>
              {readyDs.map((d) => (
                <option key={d.id} value={d.id}>
                  {fmtTime(d.created_at)} · 학습 {d.train_count} / 평가 {d.eval_count}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </Advanced>
      <RunAction
        canExecute={canExec}
        label="모델 등록"
        onRun={submit}
        job={job}
        disabled={!ok || !nameOk || needLogChoice}
        disabledReason={!ok ? "경로를 입력하고 확인하세요" : !nameOk ? "모델 이름을 확인하세요" : "로그 파일을 고르세요"}
        error={error}
      />
      {registered && (
        <div className="result-line" data-testid="register-result">
          등록됨: <b>{registered.name}</b> v{registered.version} · <LogStatusText m={registered} />
          {registered.log_status === "PARSED" && registered.epochs_total != null && (
            <span className="small"> · {registered.epochs_total} epoch</span>
          )}
          {registered.stored_display_path && (
            <div className="codeline small">
              <code>{registered.stored_display_path}</code>
              <CopyButton text={registered.stored_display_path} label="경로 복사" />
            </div>
          )}
        </div>
      )}
      <p className="muted small">등록 시 파일을 Study 폴더로 복사합니다. 등록 후 원본 폴더는 지워도 됩니다.</p>
    </Card>
  );
}
