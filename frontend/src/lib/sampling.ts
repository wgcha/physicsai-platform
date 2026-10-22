// S15 표본 방식(phase3.md §20, D3-63) 재노출 모음 — 실제 정의는 samplingKinds(종류·이름·상한)·samplingDescs(설명문)·samplingRuns(run 수 계산)·samplingSummary(배치 머리 요약).
// 기존 `import ... from "../lib/sampling"` 경로를 그대로 쓰도록 둔다(R-F 분할, 동작 불변).
export * from "./samplingKinds";
export * from "./samplingDescs";
export * from "./samplingRuns";
export * from "./samplingSummary";
export * from "./samplingTable";
