import { useEffect, useState } from "react";
import { api, type Dataset } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, CodeLine, CopyButton, Field, RunAction } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { fmtTime } from "../../lib/format";

const DS_STATUS: Record<Dataset["status"], string> = { BUILDING: "생성 중", READY: "준비됨", FAILED: "실패" };

export function DatasetCreateCard() {
  const { study, datasets, reloadDatasets } = useStudy();
  const canExec = useCanExecute();
  const { job, run, error } = useJobRunner("DATASET_CREATE", () => void reloadDatasets());
  const [path, setPath] = useState("");
  const [inspected, setInspected] = useState<boolean>(false);
  const [seed, setSeed] = useState("");
  const [splitGroup, setSplitGroup] = useState<"file" | "parent_dir">("file");
  const [opts, setOpts] = useState({ extract_faces: true, extract_mdi: false, extract_time_history_vectors: false });

  const submit = () => {
    const params: Record<string, unknown> = { input_path: path.trim(), split_group: splitGroup, options: opts };
    if (seed.trim()) params.seed = Number(seed);
    void run(params).then(() => void reloadDatasets());
  };

  return (
    <Card step="③-1" title="데이터셋 생성">
      <PathInput
        studyId={study.id}
        purpose="DATASET_INPUT"
        label="h3d 폴더 경로 (AI 루트 하위)"
        placeholder="E:/shared/AI_WORK/cushion/00_inbox/h3d"
        value={path}
        onChange={setPath}
        canExecute={canExec}
        onInspected={(r) => setInspected(!!r?.ok)}
        renderSummary={(r) => (
          <div className="summary-line">
            h3d <b>{r.summary.h3d_count ?? 0}</b>개 → 학습 <b>{r.summary.expected_train ?? "–"}</b> / 평가{" "}
            <b>{r.summary.expected_eval ?? "–"}</b> 예상
            {r.summary.sample_files && r.summary.sample_files.length > 0 && (
              <div className="mono small muted ellipsis">{r.summary.sample_files.slice(0, 3).join(", ")} …</div>
            )}
          </div>
        )}
      />
      <p className="note">
        평가용 홀드아웃 <b>10% 고정</b>(고정 seed). 평가용 데이터는 학습 패키지에 넣지 않고 점수 계산에만 씁니다.
      </p>
      <Advanced>
        <div className="form-grid">
          <Field label="seed" hint="비우면 설정 기본값">
            <input className="num" inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value.replace(/[^0-9]/g, ""))} />
          </Field>
          <Field label="분할 단위" hint="run마다 h3d가 여러 개면 상위 폴더 단위로 나누세요">
            <select value={splitGroup} onChange={(e) => setSplitGroup(e.target.value as "file" | "parent_dir")}>
              <option value="file">파일</option>
              <option value="parent_dir">상위 폴더</option>
            </select>
          </Field>
        </div>
        <div className="checks">
          {(
            [
              ["extract_faces", "면(face) 추출"],
              ["extract_mdi", "MDI 추출"],
              ["extract_time_history_vectors", "시간이력 벡터 추출"],
            ] as const
          ).map(([k, l]) => (
            <label key={k} className="check">
              <input type="checkbox" checked={opts[k]} onChange={(e) => setOpts({ ...opts, [k]: e.target.checked })} /> {l}
            </label>
          ))}
        </div>
      </Advanced>
      <RunAction
        canExecute={canExec}
        label="데이터셋 생성"
        onRun={submit}
        job={job}
        disabled={!path.trim() || !inspected}
        disabledReason="경로를 입력하고 확인하세요"
        error={error}
      />
      {datasets.length > 0 && (
        <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>상태</th>
              <th className="num">h3d</th>
              <th className="num">학습 / 평가</th>
              <th>분할</th>
              <th>입력 폴더</th>
              <th>생성</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((d) => (
              <tr key={d.id}>
                <td>
                  <span className={`ds-status ${d.status.toLowerCase()}`}>{DS_STATUS[d.status]}</span>
                </td>
                <td className="num">{d.h3d_count ?? "–"}</td>
                <td className="num">
                  {d.train_count ?? "–"} / {d.eval_count ?? "–"}
                </td>
                <td className="small">
                  {Math.round(d.holdout_ratio * 100)}% · {d.split_group === "file" ? "파일" : "폴더"} · seed {d.seed}
                </td>
                <td className="mono small ellipsis" title={d.dataset_display_path ? `입력: ${d.source_path}\n데이터셋: ${d.dataset_display_path}` : d.source_path}>
                  {d.source_path}
                </td>
                <td className="small wrap-date">
                  {d.created_by_name} · {fmtTime(d.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </Card>
  );
}

const DEFAULT_COMMANDS = [
  "edspy --physicsai --train <MODEL_NAME>.psmdl --dataset dataset_train.psdata --spec <SETTINGS>.pscfg > train.log 2>&1",
  "edspy --physicsai --train <MODEL_NAME>.psmdl --dataset dataset_train.psdata --spec <SETTINGS>.pscfg --pretrained-model <PRETRAINED>.psmdl > train.log 2>&1",
];

export function PackageExportCard() {
  const { datasets, reloadDatasets } = useStudy();
  const canExec = useCanExecute();
  const ready = datasets.filter((d) => d.status === "READY");
  const [dsId, setDsId] = useState<string>("");
  const { job, run, error } = useJobRunner("PACKAGE_EXPORT", () => void reloadDatasets());
  const [commands, setCommands] = useState<string | null>(null);

  const selected = ready.find((d) => d.id === dsId) ?? ready[0];
  useEffect(() => {
    if (!dsId && ready[0]) setDsId(ready[0].id);
  }, [dsId, ready]);

  useEffect(() => {
    setCommands(null);
    if (!job || job.state !== "SUCCEEDED") return;
    let alive = true;
    api
      .artifacts(job.id)
      .then(async (arts) => {
        const a = arts.find((x) => x.kind === "PACKAGE_COMMANDS");
        if (!a) return;
        const text = await (await api.artifactBlob(a.id)).text();
        if (alive) setCommands(text);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [job?.id, job?.state]);

  const pkgPath = selected?.package_display_path ?? "";
  const cmdLines = commands
    ? commands.split(/\r?\n/).filter((l) => l.trim() && !l.trim().startsWith("#"))
    : DEFAULT_COMMANDS;

  return (
    <Card step="③-2" title="학습 패키지 내보내기">
      {ready.length === 0 ? (
        <p className="muted">준비된 데이터셋이 없습니다. ③-1에서 먼저 만드세요.</p>
      ) : (
        <Field label="데이터셋">
          <select value={selected?.id ?? ""} onChange={(e) => setDsId(e.target.value)}>
            {ready.map((d) => (
              <option key={d.id} value={d.id}>
                {fmtTime(d.created_at)} · 학습 {d.train_count} / 평가 {d.eval_count}
                {d.package_ready ? " · 내보냄" : ""}
              </option>
            ))}
          </select>
        </Field>
      )}
      <RunAction
        canExecute={canExec}
        label="학습 패키지 내보내기"
        onRun={() => selected && void run({ dataset_id: selected.id })}
        job={job}
        disabled={!selected}
        disabledReason="준비된 데이터셋이 필요합니다"
        error={error}
      />
      {selected?.package_ready && pkgPath && (
        <div className="package">
          <div className="field-label">패키지 폴더</div>
          <div className="codeline">
            <code>{pkgPath}</code>
            <CopyButton text={pkgPath} />
          </div>
          <div className="field-label">학습 명령 예시 {commands ? "(COMMANDS.txt)" : ""}</div>
          {cmdLines.map((l, i) => (
            <CodeLine key={i} text={l} />
          ))}
          <p className="muted small">dataset_train.psdata는 학습용입니다(평가용 홀드아웃 제외). 단위계 mm-ton-s.</p>
        </div>
      )}
    </Card>
  );
}

export function HpcTrainingNotice() {
  const { study } = useStudy();
  return (
    <Card step="③-3" title="HPC에서 직접 학습" className="notice-card">
      <ol className="steps-text">
        <li>③-2 패키지 폴더를 HPC로 가져가 학습 명령을 실행합니다.</li>
        <li>
          학습 후 <code>.psmdl</code>·<code>.pscfg</code>·<code>train.log</code>를 한 폴더에 모아 AI 루트 아래로 옮기고 ③-4에서 등록합니다.
        </li>
      </ol>
      {study.folder_display_path && (
        <div className="codeline small" title="Study 폴더">
          <code>{study.folder_display_path}</code>
          <CopyButton text={study.folder_display_path} label="경로 복사" />
        </div>
      )}
      <p className="muted small">플랫폼은 학습을 실행하지 않으며 실시간 로그도 받지 않습니다.</p>
    </Card>
  );
}
