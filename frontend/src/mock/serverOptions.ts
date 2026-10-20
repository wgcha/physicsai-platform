// 메모리 목 서버 생성 옵션(MockOptions)·기본 /status.ui 값·공유 폴더 루트(R-F 분할, server.ts에서 재노출).
import type { FeatureKey } from "../api/types";
import { type MockUserKey } from "./data";
import { type CaptureMode } from "./capture";

export interface MockOptions {
  user?: MockUserKey;
  hpcConfigured?: boolean;
  /** phase3 §16 SCX(D3-58): hpcConfigured일 때 게이트웨이 모드(기본 command) */
  hpcMode?: "command" | "scx";
  /** SCX 시드: 진행 중 ① 제출의 한 run을 결과 모름(SUBMISSION_UNKNOWN)으로 */
  scxUnknown?: boolean;
  /** 실행 중 작업이 tick마다 진행되는 정도(%) */
  speed?: number;
  /** /status.ui 값(B1). 시험에서 짧은 주기를 주입 */
  ui?: Record<string, number>;
  /** 2차: 비활성 기능(/status.features enabled=false). 기본 ["train_resp"](response_extract 템플릿 null) */
  disabledFeatures?: FeatureKey[];
  /** C18: PBS 취소 명령 실패 흉내 */
  hpcCancelFails?: boolean;
  /** /status.demo(시연 모드) */
  demo?: boolean;
  /** /status.config.warnings */
  configWarnings?: string[];
  /** /status.auth.login_url(auth.dashboard_public_login_url, 운영 대시보드 기본 "/home/" — phase3 D3-38) */
  loginUrl?: string;
  /** S9: "running"이면 진행 중 일괄 예측 B-003 시드(하위 PREDICT 12개가 대기열에 들어간다) */
  batchDemo?: "running" | "sobol" | "bbd";
  /** S10: 예측 끝 컨투어 캡처 결과(기본 OK) */
  capture?: CaptureMode;
  /** S16 V1: "history"면 단일 예측 이력 시드(템플릿·준비된 입력·재시도·실패·진행 중) */
  predictRuns?: "history";
  /** S16 V2: "demo"면 FEM 검증 시드(FV-001 완료·FV-002 실패·FV-003 동반 예측 대기) */
  femVerify?: "demo";
  /** S18: /status.limits.configured.doe_generator_default(기본 platform — 설정 train_data.doe_generator_default) */
  doeGenerator?: "platform" | "hyperstudy";
}

export const MOCK_AI_ROOT = "E:\\shared\\AI_WORK";
export const DEFAULT_UI = {
  max_artifact_bytes: 20971520,
  poll_job_running_ms: 2000,
  poll_job_queued_ms: 5000,
  poll_job_waiting_hpc_ms: 15000,
  poll_log_ms: 2000,
  poll_queue_ms: 5000,
  poll_resources_ms: 10000,
  poll_notifications_ms: 10000,
  poll_status_ms: 30000,
};
