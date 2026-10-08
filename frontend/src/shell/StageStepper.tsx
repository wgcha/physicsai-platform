import { Link } from "react-router-dom";
import type { JobState } from "../api";
import { STAGES, STAGE_MARK } from "../lib/format";
import { StateDot } from "../components/ui";

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
      {STAGES.map((s) => (
        <li key={s.n} className={`step ${s.n === current ? "current" : ""}`}>
          <Link to={`${base}/stage/${s.n}`} aria-current={s.n === current ? "step" : undefined}>
            <span className="step-mark">{STAGE_MARK[s.n]}</span>
            <span className="step-name">{s.name}</span>
            <StateDot state={stageStates[s.n]} />
          </Link>
        </li>
      ))}
    </ol>
  );
}

