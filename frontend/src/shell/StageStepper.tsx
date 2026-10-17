import { Link } from "react-router-dom";
import type { JobState } from "../api";
import { JOB_STATE_LABEL, STAGES, STAGE_MARK } from "../lib/format";
import { StateDot } from "../components/ui";

/** 단계 탐색(대시보드 톤, 2026-10-17): 작은 단계 버튼 ①~⑤ — 현재 단계 accent 테두리·selected 바탕, 최근 작업 상태 점 */
export function StageStepper({
  base,
  current,
  stageStates,
}: {
  base: string;
  current: number;
  stageStates: Record<number, JobState | null | undefined>;
}) {
  return (
    <ol className="stepper" aria-label="단계">
      {STAGES.map((s) => {
        const on = s.n === current;
        const st = stageStates[s.n];
        return (
          <li key={s.n} className={`step ${on ? "current" : ""}`}>
            <Link to={`${base}/stage/${s.n}`} aria-current={on ? "step" : undefined}>
              <span className="step-mark">{STAGE_MARK[s.n]}</span> <span className="step-name">{s.name}</span>
              {st && <span className="step-state sr-only"> · {JOB_STATE_LABEL[st]}</span>}
              <StateDot state={st} />
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
