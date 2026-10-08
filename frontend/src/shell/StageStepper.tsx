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
        <li key={s.n} className={`step ${s.n === current ? "current" : ""} ${s.active ? "" : "deferred"}`}>
          <Link to={`${base}/stage/${s.n}`} aria-current={s.n === current ? "step" : undefined}>
            <span className="step-mark">{STAGE_MARK[s.n]}</span>
            <span className="step-name">{s.name}</span>
            {s.active ? <StateDot state={stageStates[s.n]} /> : <span className="step-later">2차</span>}
          </Link>
        </li>
      ))}
    </ol>
  );
}

export function DeferredStageNotice({ n }: { n: number }) {
  const s = STAGES.find((x) => x.n === n);
  return (
    <div className="deferred-notice" role="note">
      <div className="deferred-mark">{STAGE_MARK[n]}</div>
      <h2>{s?.name}</h2>
      <p>2차에서 제공 예정입니다.</p>
      <p className="muted small">1차에서는 ③ 데이터셋·모델과 ④ 단일 예측을 사용할 수 있습니다.</p>
    </div>
  );
}
