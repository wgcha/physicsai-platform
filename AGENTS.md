# AGENTS.md — 저장소 작업 규칙

구조 지도: [docs/architecture.md](docs/architecture.md) (파일 위치는 이 문서 우선). 계약: 1차 [docs/contracts/platform.md](docs/contracts/platform.md), 2차 [docs/contracts/phase2.md](docs/contracts/phase2.md)(2차가 바꾸는 1차 규칙은 phase2.md §2.3, 2차 문서 우선). 계약과 다르게 구현해야 하면 먼저 Plan에 계약 수정을 요청한다(해당 문서 끝 "변경 메모"에 기록).

## 역할 분리

| 역할 | 수정 가능 범위 |
|---|---|
| Plan | `docs/**`, `AGENTS.md`, `README.md` (애플리케이션 코드 작성 금지) |
| Impl-Backend | `pyproject.toml`, `backend/**`, `worker/**`, `migrations/**`, `config/**`, `scripts/**`, `deploy/**`, `packages/**`(paicad 제외), `.github/**`, `.gitignore` |
| Impl-Geom | `packages/paicad/**` (형상 엔진, 계약 [docs/contracts/geometry-engine.md](docs/contracts/geometry-engine.md)) |
| Impl-Frontend | `frontend/**`, `frontend-dist/**`(빌드본 — `scripts/build-frontend-dist`로만 생성) |
| Verifier | 수정 없음. platform.md §22(1차)와 phase2.md §20(2차, V2-*) 체크리스트로 판정하고 결과를 보고 |

- 에이전트 정의·모델: `.claude/agents/*.md`(pai-explore=haiku, pai-plan·impl-geom·verifier=opus, impl-backend·impl-frontend=sonnet). 위임 시 이 이름을 쓴다.
- 토큰: 메인은 diff를 읽지 않고 요약·판정으로 판단. 반환 상한 explore 15줄, plan 30줄, impl 10줄, verifier 20줄. 큰 파일·로그는 grep/head/tail.
- 남의 소유 파일은 고치지 말고 요청한다. API 모양 변경 순서: 계약 수정(Plan) → `backend/openapi.json` 갱신(Backend) → 프런트 반영.

## 필수

- **테스트 필수**: 기능 변경마다 자동 시험을 함께 넣는다. `scripts/test-all`이 Linux(Altair 없음, PostgreSQL 있음)에서 통과해야 완료. 실제 Altair가 필요한 동작은 가짜 도구(`backend/tests/fake_tools/`)로 시험하고, Windows 전용 시험의 skip은 통과로 치지 않는다.
- **하드코딩 금지**: Altair·PBS 실행 파일 경로, 명령 인자, AI 루트, 포트, 정규식은 `config`에서만 읽는다. 코드에 `Program Files` 경로 금지.
- **SPDM 보호**: SPDM master에 쓰지 않는다(2차 가져오기도 읽기·복사만, 하드링크 금지). 산출물은 AI 루트에만. 사용자 산출물은 삭제하지 않고 `_backup`으로 이동한다.
- **보안**: 외부 명령은 워커에서만, `shell=False` 인자 배열로. pickle(`.pscfg`)을 열지 않는다. 원본 pyd 코어를 플랫폼 프로세스에서 import하지 않는다(런처를 Altair 도구가 실행). 업로드 엔드포인트를 만들지 않는다. 대시보드 세션 토큰을 로그·DB에 남기지 않는다.
- **paicad 버전**: `packages/paicad`를 바꾸는 커밋마다 `__version__`(`packages/paicad/src/paicad/__init__.py`, 단일 출처)을 올리고 `packages/paicad/CHANGELOG.md` 최상단에 항목을 추가한다(geometry-engine.md §17, `scripts/test-all`이 검사).
- DB에는 경로·상태·수치 요약만. 파일 본문 저장 금지.
- 사용자 표시 문구·오류 메시지는 한국어.
- **프런트 빌드본 함께 커밋**: `frontend/`(src·public·index.html·package*.json·vite.config·tsconfig)를 고치면 `scripts/build-frontend-dist` 실행 후 `frontend-dist/`를 함께 커밋한다(서버는 Node 없이 이 빌드본을 배치 — phase3 D3-40). `scripts/test-all`이 최신 여부를 검사한다. Impl-Frontend가 프런트 커밋에 함께 넣는다.
- **빌드본 도구 소유**: `scripts/build-frontend-dist`·`scripts/frontend_source_hash.py` 변경은 Impl-Frontend와 협의한다(규칙이 바뀌면 빌드본 판정이 바뀜). `frontend-dist/` 재생성·커밋은 프런트 변경과 같은 커밋에서(Impl-Frontend 소유).
- **설치 스크립트는 관리자 권한 없이**: 머신 환경변수·관리자 확인을 쓰지 않는다. 비밀값은 런타임 파일(`<런타임>\secrets\`)에만, 작업 실행 인자에는 경로만(phase3 D3-41).

## 커밋 규칙

- 작은 단위로, 제목 한 줄(한국어 또는 영어, 72자 이내) + 필요 시 본문에 계약 절 번호(`platform.md §8.4`).
- 커밋 전 `scripts/test-all` 통과. 실패한 채로 커밋하지 않는다.
- 비밀값·`config/platform.yaml`·대용량 산출물(`*.psdata`, `*.psmdl`, `*.h3d`)을 커밋하지 않는다.
- 메인 에이전트가 지시하지 않으면 push하지 않는다.
