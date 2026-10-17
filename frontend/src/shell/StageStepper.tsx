import { Link } from "react-router-dom";
import type { JobState } from "../api";
import { JOB_STATE_LABEL, STAGES, STAGE_MARK } from "../lib/format";
import { StateDot } from "../components/ui";

/** 단계 탐색(대시보드 톤, 2026-10-17 D3-55·D3-56): 단계 버튼 ①~⑤ — 내용 폭을 5등분해 꽉 채움(높이 52),
 *  번호는 원 문자(①) 대신 숫자 배지(Pretendard에서 원 문자가 작게 보임, 읽기용 이름은 "① 학습데이터 생성" 그대로),
 *  현재 단계 accent 테두리·selected 바탕·accent 배지, 최근 작업 상태 점 */
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
              <span className="step-num" aria-hidden="true">
                {s.n}
              </span>
              <span className="sr-only">{STAGE_MARK[s.n]}</span> <span className="step-name">{s.name}</span>
              {st && <span className="step-state sr-only"> · {JOB_STATE_LABEL[st]}</span>}
              <StateDot state={st} />
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
