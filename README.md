# PhysicsAI 플랫폼

Altair PhysicsAI(edspy) 기반 해석 대리모델의 데이터셋·모델 관리와 단일 예측을 웹에서 수행하는 사내 플랫폼. 사내 해석 대시보드와 같은 Windows Server에서 `/physicsai/` 하위 경로로 동작하고 대시보드 로그인을 공유한다.

- 1차 범위: 대기열·워커(로컬 슬롯 1개, Windows Job Object 자원 제한), ③ 데이터셋·모델(데이터셋 생성 → 학습 패키지 → HPC 학습(외부) → 모델 등록 → 평가·Final), ④ 단일 예측, 알림, 공통 셸
- 2차: ① 학습데이터 생성, ② 데이터 정리, ⑤ 최적화, PBS 실제 연동, 오프라인 배포
- 단위계: mm-ton-s (변환 없음)

문서: [계약](docs/contracts/platform.md) · [결정 기록](docs/decisions.md) · [사용자 E2E 체크리스트](docs/e2e-checklist.md) · [작업 규칙](AGENTS.md)

## 디렉터리 구조(예정)

```text
backend/     FastAPI 백엔드(physicsai_api)와 API·워커 공용 코어(physicsai_core), 시험·가짜 도구
worker/      별도 워커 프로세스(physicsai_worker): 대기열 claim, 외부 프로그램 실행, 자원 제한
migrations/  Alembic(PostgreSQL 전용)
frontend/    React + Vite + TypeScript (base /physicsai/)
config/      platform.example.yaml (설정 스키마 예시)
scripts/     개발 실행·DB 초기화·전체 시험 스크립트(.ps1 / .sh)
docs/        계약·결정·체크리스트
```

## 개발 실행(예정)

`scripts/dev-db-init` → `scripts/dev-backend`(127.0.0.1:8100) → `scripts/dev-worker` → `scripts/dev-frontend`(127.0.0.1:5174/physicsai/). 대시보드 개발 서버(127.0.0.1:5173)에 먼저 로그인한다. 자세한 내용은 계약 §4.6.
