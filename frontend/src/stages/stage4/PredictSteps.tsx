// ④ 템플릿 값 입력의 "진행"(phase3.md §14.8, 사용자 결정 2026-10-16):
// 조립 포함 = 형상 생성 → 메시 연결 → 조립 → 예측 → 결과, 메시 단독 = 형상 생성 → 예측 → 결과(메시 연결·조립 없음).
import type { InputKind, Job, JobStep } from "../../api";

interface Group {
  label: string;
  tool?: string;
  keys: string[];
}

const RESULT_KEYS = ["CONTOUR_PREVIEW", "CURVE_PICK", "RESPONSE_EXTRACT", "RESPONSE_TABLE"];

/** step 묶음. mesh_only(쿠션 입력)의 RAD_ASSEMBLE은 복사만이라 형상 생성에 넣는다(MESH는 Altair 쿠션이면 SKIPPED, Native 쿠션이면 모핑 — 같은 묶음) */
export function stepGroups(kind: InputKind): Group[] {
  return kind === "mesh_only"
    ? [
        { label: "형상 생성", tool: "SimLab", keys: ["PR_PREP", "TPL_RENDER", "GEOM_UPDATE", "MESH", "RAD_ASSEMBLE"] },
        { label: "예측", tool: "PhysicsAI", keys: ["EDSPY_PREDICT"] },
        { label: "결과", keys: RESULT_KEYS },
      ]
    : [
        { label: "형상 생성", tool: "SimLab", keys: ["PR_PREP", "TPL_RENDER", "GEOM_UPDATE"] },
        { label: "메시 연결", tool: "HyperMesh", keys: ["MESH"] },
        { label: "조립", tool: "Radioss 입력", keys: ["RAD_ASSEMBLE"] },
        { label: "예측", tool: "PhysicsAI", keys: ["EDSPY_PREDICT"] },
        { label: "결과", keys: RESULT_KEYS },
      ];
}

type St = "wait" | "run" | "done" | "skip" | "fail" | "cancel";

function groupState(steps: JobStep[]): St {
  if (!steps.length) return "wait";
  if (steps.some((s) => s.state === "FAILED")) return "fail";
  if (steps.some((s) => s.state === "RUNNING")) return "run";
  if (steps.some((s) => s.state === "CANCELED")) return "cancel";
  if (steps.every((s) => s.state === "SKIPPED")) return "skip";
  if (steps.every((s) => s.state === "SUCCEEDED" || s.state === "SKIPPED")) return "done";
  if (steps.some((s) => s.state === "SUCCEEDED")) return "run";
  return "wait";
}

/** 소요: 1분 12초 / 18초 */
export function fmtDuration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}초`;
  const m = Math.floor(s / 60);
  return s % 60 ? `${m}분 ${s % 60}초` : `${m}분`;
}

function duration(steps: JobStep[]): string | null {
  const st = steps.map((s) => (s.started_at ? Date.parse(s.started_at) : NaN)).filter(Number.isFinite);
  const fn = steps.map((s) => (s.finished_at ? Date.parse(s.finished_at) : NaN)).filter(Number.isFinite);
  if (!st.length || !fn.length) return null;
  return fmtDuration(Math.max(...fn) - Math.min(...st));
}

const TEXT: Record<St, string> = { wait: "대기", run: "실행 중", done: "완료", skip: "건너뜀", fail: "실패", cancel: "취소" };

export function PredictSteps({ job, kind }: { job: Job | null; kind: InputKind }) {
  const groups = stepGroups(kind);
  return (
    <ol className="psteps" aria-label="예측 실행 단계">
      {groups.map((g, i) => {
        const steps = job ? job.steps.filter((s) => g.keys.includes(s.step_key)) : [];
        const st = groupState(steps);
        const failed = steps.find((s) => s.state === "FAILED");
        const d = st === "done" ? duration(steps) : null;
        return (
          <li key={g.label} className={`pstep ${st}`} title={failed ? `${failed.step_key}: ${failed.failure_code ?? ""} ${failed.failure_message ?? ""}` : undefined}>
            <span className="pstep-label">
              {i + 1} {g.label}
              {g.tool ? `(${g.tool})` : ""}
            </span>
            <span className="pstep-state">{d ? `${TEXT[st]} · ${d}` : TEXT[st]}</span>
          </li>
        );
      })}
    </ol>
  );
}
