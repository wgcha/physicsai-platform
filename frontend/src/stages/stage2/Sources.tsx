import { useEffect, useState } from "react";
import { api, type Artifact, type Job } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Card, RunAction } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { FeatureGate } from "../../components/FeatureGate";
import { fmtBytes, fmtTime } from "../../lib/format";
import { useCuration, type SourceMode } from "./CurationContext";

/** 작업 산출물 중 JSON 파일들을 이름 → 내용으로 읽는다(미리보기 결과 등, B18) */
export function useJobJson(job: Job | null, kinds: Artifact["kind"][]): Record<string, unknown> | null {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const id = job?.state === "SUCCEEDED" ? job.id : null;
  const kindKey = kinds.join(",");
  useEffect(() => {
    setData(null);
    if (!id) return;
    let alive = true;
    (async () => {
      const arts = (await api.artifacts(id)).filter((a) => kindKey.split(",").includes(a.kind));
      const out: Record<string, unknown> = {};
      for (const a of arts) {
        try {
          out[a.file_name] = JSON.parse(await (await api.artifactBlob(a.id)).text());
        } catch {
          /* 형식 오류는 건너뜀 */
        }
      }
      if (alive) setData(out);
    })().catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [id, kindKey]);
  return data;
}

const MODES: { m: SourceMode; label: string }[] = [
  { m: "TRAIN_DOE", label: "① DOE 결과" },
  { m: "SPDM_IMPORT", label: "SPDM 가져오기" },
  { m: "FOLDER", label: "폴더 경로" },
];

/** 상단 원천 선택(§14.3) */
export function SourcePicker() {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const c = useCuration();
  const does = c.sources.filter((s) => s.kind === "TRAIN_DOE");
  const imps = c.imports.filter((i) => i.status === "READY");
  return (
    <Card title="원천 선택" className="wide source-card">
      <div className="source-row">
        <div className="seg" role="radiogroup" aria-label="원천">
          {MODES.map(({ m, label }) => (
            <button key={m} type="button" role="radio" aria-checked={c.mode === m} className={c.mode === m ? "on" : ""} onClick={() => c.setMode(m)}>
              {label}
            </button>
          ))}
        </div>
        <div className="source-pick">
          {c.mode === "TRAIN_DOE" &&
            (does.length ? (
              <select value={c.doeId} onChange={(e) => c.setDoeId(e.target.value)} aria-label="DOE 결과">
                {does.map((s) => (
                  <option key={s.ref_id} value={s.ref_id}>
                    {s.label} · {fmtTime(s.created_at)}
                  </option>
                ))}
              </select>
            ) : (
              <span className="muted small">회수된 ① DOE 결과가 없습니다(①-5 먼저)</span>
            ))}
          {c.mode === "SPDM_IMPORT" &&
            (imps.length ? (
              <select value={c.importId} onChange={(e) => c.setImportId(e.target.value)} aria-label="SPDM 가져오기">
                {imps.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.spdm_path} · {i.file_count}개 · {fmtTime(i.created_at)}
                  </option>
                ))}
              </select>
            ) : (
              <span className="muted small">
                {c.imports.some((i) => i.status === "BUILDING") ? "가져오는 중입니다…" : "가져온 SPDM 결과가 없습니다(②-0에서 가져오기)"}
              </span>
            ))}
          {c.mode === "FOLDER" && (
            <PathInput
              studyId={study.id}
              purpose="CURATION_INPUT"
              label="결과 폴더 경로 (AI 루트 하위)"
              placeholder="E:/shared/AI_WORK/cushion/00_inbox/results"
              value={c.folder.path}
              onChange={(v) => c.setFolder({ ...c.folder, path: v, ok: false })}
              canExecute={canExec}
              onInspected={(r) => c.setFolder({ path: c.folder.path, ok: !!r?.ok, h3d: Number(r?.summary.h3d_count ?? 0), t01: Number(r?.summary.t01_count ?? 0) })}
              renderSummary={(r) => (
                <div className="summary-line">
                  h3d <b>{String(r.summary.h3d_count ?? 0)}</b> · T01 <b>{String(r.summary.t01_count ?? 0)}</b>
                </div>
              )}
            />
          )}
        </div>
        {c.sourceInfo && (
          <div className="source-counts" data-testid="source-counts">
            <span>
              h3d <b>{c.sourceInfo.h3d}</b>
            </span>
            <span>
              T01 <b>{c.sourceInfo.t01}</b>
            </span>
            {c.sourceInfo.runsExpected != null && (
              <span>
                기대 run <b>{c.sourceInfo.runsExpected}</b>
              </span>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

/** ②-0 SPDM 가져오기(읽기 전용 복사, §6.11) */
export function SpdmImportCard({ initialPath = "" }: { initialPath?: string }) {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const c = useCuration();
  const { job, run, error } = useJobRunner("SPDM_IMPORT", () => void c.reload());
  const [path, setPath] = useState(initialPath);
  const [ok, setOk] = useState(false);
  return (
    <Card step="②-0" title="SPDM 가져오기">
      <PathInput
        studyId={study.id}
        purpose="SPDM_IMPORT"
        label="SPDM 경로 (읽기 전용)"
        placeholder="\\spdm\master\PRJ\Case_0012\Scene_03"
        value={path}
        onChange={setPath}
        canExecute={canExec}
        onInspected={(r) => setOk(!!r?.ok)}
        renderSummary={(r) => <SpdmSummary s={r.summary} />}
      />
      <FeatureGate feature="spdm_import">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label="가져오기"
            onRun={() => void run({ spdm_path: path.trim() }).then(() => void c.reload())}
            job={job}
            disabled={!enabled || !ok}
            disabledReason={enabled ? "SPDM 경로를 입력하고 확인하세요" : undefined}
            error={error}
          />
        )}
      </FeatureGate>
      {c.imports.length > 0 && (
        <div className="table-wrap">
          <table className="table compact" aria-label="가져오기 목록">
            <thead>
              <tr>
                <th>SPDM 경로</th>
                <th className="num">파일</th>
                <th className="num">크기</th>
                <th>상태</th>
                <th>시각</th>
              </tr>
            </thead>
            <tbody>
              {c.imports.map((i) => (
                <tr key={i.id}>
                  <td className="mono small ellipsis" title={`${i.spdm_path}\n→ ${i.dest_display_path}`}>
                    {i.spdm_path}
                  </td>
                  <td className="num">{i.file_count ?? "–"}</td>
                  <td className="num small">{fmtBytes(i.total_bytes)}</td>
                  <td className={`ds-status ${i.status.toLowerCase()}`}>{i.status === "READY" ? "준비됨" : i.status === "BUILDING" ? "가져오는 중" : "실패"}</td>
                  <td className="small wrap-date">{fmtTime(i.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">SPDM 원본은 읽기만 합니다. 공백·특수문자가 든 이름은 복사본에서 정리됩니다.</p>
    </Card>
  );
}

export function SpdmSummary({ s }: { s: Record<string, unknown> }) {
  return (
    <div className="summary-line">
      h3d <b>{String(s.h3d_count ?? 0)}</b> · T01 <b>{String(s.t01_count ?? 0)}</b> · {fmtBytes(Number(s.total_bytes ?? 0))}
      {Number(s.renamed_count ?? 0) > 0 && <span className="muted"> · 이름 정리 {String(s.renamed_count)}개</span>}
    </div>
  );
}
