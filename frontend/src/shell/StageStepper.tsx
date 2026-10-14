import { Link } from "react-router-dom";
import type { JobState } from "../api";
import { JOB_STATE_LABEL, STAGES, STAGE_MARK } from "../lib/format";
import { StateDot } from "../components/ui";

/** 단계 표시: 큰 번호 01~05(Display) + 이름·상태(Reference), 세로 구분선, 현재 단계 위쪽 빨간 4px */
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
              <span className={`step-no D ${on ? "red" : "mute"}`} aria-hidden="true">
                {String(s.n).padStart(2, "0")}
              </span>
              <span className="step-label R">
                <span className="step-mark">{STAGE_MARK[s.n]}</span> <span className="step-name">{s.name}</span>
                {st && <span className="step-state"> · {JOB_STATE_LABEL[st]}</span>}
                <StateDot state={st} />
              </span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
