import { Link } from "react-router-dom";
import type { JobState } from "../api";
import { JOB_STATE_LABEL, STAGES, stageCircled, stageNo } from "../lib/format";
import { StateDot } from "../components/ui";

/** 단계 탐색(대시보드 톤, 2026-10-17 D3-55·D3-56 + S14 D3-62): 단계 버튼 ①~⑥(표시 순서 1·2·3·4·결과분석·5) — 내용 폭을 6등분해 꽉 채움(높이 52),
 *  번호는 원 문자(①) 대신 숫자 배지(Pretendard에서 원 문자가 작게 보임, 읽기용 이름은 "① 학습데이터 생성"·"⑤ 결과분석"·"⑥ 최적화"),
 *  현재 단계 accent 테두리·selected 바탕·accent 배지, 최근 작업 상태 점. URL 숫자(/stage/4·/stage/5)는 불변, 결과분석은 /stage/analysis */
export function StageStepper({
  base,
  current,
  stageStates,
}: {
  base: string;
  /** 현재 단계의 URL 끝(1~5 또는 analysis) */
  current: string;
  stageStates: Record<number, JobState | null | undefined>;
}) {
  return (
    <ol className="stepper" aria-label="단계">
      {STAGES.map((s) => {
        const on = s.path === current;
        const st = s.n === null ? null : stageStates[s.n];
        return (
          <li key={s.path} className={`step ${on ? "current" : ""}`}>
            <Link to={`${base}/stage/${s.path}`} aria-current={on ? "step" : undefined}>
              <span className="step-num" aria-hidden="true">
                {stageNo(s.path)}
              </span>
              <span className="sr-only">{stageCircled(s.path)}</span> <span className="step-name">{s.name}</span>
              {st && <span className="step-state sr-only"> · {JOB_STATE_LABEL[st]}</span>}
              <StateDot state={st} />
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
