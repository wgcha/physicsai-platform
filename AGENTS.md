# AGENTS.md — 저장소 작업 규칙

구조 지도: [docs/architecture.md](docs/architecture.md) (파일 위치는 이 문서 우선). 계약: 1차 [docs/contracts/platform.md](docs/contracts/platform.md), 2차 [docs/contracts/phase2.md](docs/contracts/phase2.md)(2차가 바꾸는 1차 규칙은 phase2.md §2.3, 2차 문서 우선). 계약과 다르게 구현해야 하면 먼저 Plan에 계약 수정을 요청한다(해당 문서 끝 "변경 메모"에 기록). 릴리스 범위·병합 순서·migration 번호: [docs/roadmap.md](docs/roadmap.md)(v0.2.7 → v0.2.8 순차).

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
- **보안**: 외부 명령은 워커에서만, `shell=False` 인자 배열로. pickle(`.pscfg`)을 열지 않는다. 원본 pyd 코어를 플랫폼 프로세스에서 import하지 않는다(런처를 Altair 도구가 실행). 대시보드 세션 토큰·API 토큰(`pai_…`)·확인 토큰(`pcf_…`) 평문을 로그·DB·감사·오류 메시지에 남기지 않는다(API 토큰은 sha256과 접두 `pai_<id8>`만).
- **업로드**(2026-10-21, [docs/contracts/upload-report.md](docs/contracts/upload-report.md)): 브라우저 분할 업로드 세션(`/uploads*`)만 허용하고 다른 업로드 경로는 만들지 않는다. 저장은 설정된 업로드 루트(`<ai_root>/<storage.upload_root>`) 아래 본인 세션 폴더로만, SPDM master 쓰기 금지 유지. multipart 금지(청크 PUT `application/octet-stream`, multipart 라우트 0개 — python-multipart는 MCP SDK 전이 의존으로만 설치되고 플랫폼 코드는 import 금지, upload-report UR-C1). purpose별 허용 패턴 + 항상 거부(`*.pscfg` pickle·`*.psdata`·실행/스크립트·`*.part`), 파일·세션·파일 수 크기 상한, 디스크 여유 검사, 청크 sha256·파일 sha256 확인, `.part`로 받은 뒤 최종 이름으로 바꾸고 기존 파일 덮어쓰기 금지, 이름 규칙은 경로 규칙과 같게(공백·cmd 메타문자·`..`·링크 거부, realpath가 세션 폴더 안). 삭제 대신 `_backup` 이동(취소·낡음·불일치), 완료된 업로드는 옮기지 않는다. 쓰기는 해당 Study 프로젝트 power 이상 + CSRF 헤더, 대시보드 쿠키 인증만(업로드 API는 `x-mcp.exclude` — API 토큰 403). 업로드·청크 로그에 쿠키·세션 토큰·파일 내용을 남기지 않는다.
- **paicad 버전**: `packages/paicad`를 바꾸는 커밋마다 `__version__`(`packages/paicad/src/paicad/__init__.py`, 단일 출처)을 올리고 `packages/paicad/CHANGELOG.md` 최상단에 항목을 추가한다(geometry-engine.md §17, `scripts/test-all`이 검사).
- DB에는 경로·상태·수치 요약만. 파일 본문 저장 금지.
- 사용자 표시 문구·오류 메시지는 한국어.
- **프런트 빌드본 함께 커밋**: `frontend/`(src·public·index.html·package*.json·vite.config·tsconfig)를 고치면 `scripts/build-frontend-dist` 실행 후 `frontend-dist/`를 함께 커밋한다(서버는 Node 없이 이 빌드본을 배치 — phase3 D3-40). `scripts/test-all`이 최신 여부를 검사한다. Impl-Frontend가 프런트 커밋에 함께 넣는다.
- **빌드본 도구 소유**: `scripts/build-frontend-dist`·`scripts/frontend_source_hash.py` 변경은 Impl-Frontend와 협의한다(규칙이 바뀌면 빌드본 판정이 바뀜). `frontend-dist/` 재생성·커밋은 프런트 변경과 같은 커밋에서(Impl-Frontend 소유).
- **MCP 토큰·Bearer**(v0.2.4, [docs/contracts/mcp.md](docs/contracts/mcp.md)): 기계 인증은 사용자별 API 토큰 `Bearer pai_…`만 — 대시보드로 introspect하지 않고 토큰 테이블로 검증, 기한 최대 30일(설정 상한도 30, 무기한·연장 없음), 역할 스냅숏 최대 30일, 즉시 차단은 관리자 폐기. 토큰은 `x-mcp.tool` operation만 허용(그 밖 403), 토큰 관리 API는 세션 전용, 토큰 요청은 CSRF 면제·`api_audit` 기록(본문 저장 금지). 비용 큰 작업은 plan → confirm → run. MCP 서버(`backend/physicsai_mcp/**`)는 권한 판단 없이 같은 Bearer로 백엔드 HTTP API만 부르는 얇은 래퍼(`physicsai_api`·`core`·`worker` import 금지), `/physicsai/mcp`는 `pai_` Bearer 필수·`mcp.enabled=false`면 404. 클라이언트 설정 예시·문서에 토큰 평문 금지(환경변수·토큰 파일).
- **MCP 대응(mcp.md M1 병합 후)**: 새 API는 `x-mcp`(도구 또는 제외 사유), 새 job_type은 `JOB_KINDS` 등록 또는 제외 사유, 새 결과 엔티티는 `SUMMARIES` 등록, 새 피처 약어·엔티티는 용어집 `ko` 한 줄, 도구 입력 스키마는 이식 가능 부분집합(mcp.md §9.2, Claude·Codex·Gemini 공통) — 정적 시험이 검사(mcp.md §15).
- **예측 입력 종류**(v0.2.7, [docs/contracts/input-kind.md](docs/contracts/input-kind.md)): 공개 API·화면은 `input: assembly|cushion`, 저장은 기존 `input_kind`/`template_kind`(`assembly|mesh_only`) — 변환은 `physicsai_core/stage4_predict/input_kind.py` 한 곳. 쿠션 입력 rad 이름은 두 엔진 모두 `predict.simlab_mesh_name`. ① 데이터 생성·③ 학습은 조립만(쿠션 선택 UI는 ④·⑥에만).
- **작업 대기열**(2026-10-22, [docs/contracts/job-queues.md](docs/contracts/job-queues.md)): GPU 슬롯은 동시 1개(설정으로 늘리지 않음), 자원 종류는 step 단위(`StepDef.res` cpu|gpu, INTERNAL은 중립) — 새 LOCAL·HPC_SUBMIT step은 `res`를 반드시 정하고(정적 시험), GPU는 PhysicsAI 추론 step만. 한 작업은 슬롯을 최대 1개만 쥐고 종류가 바뀌는 경계에서 반납·재진입(T17)한다. step 안에서 다른 종류 슬롯을 잡는 경로를 만들지 않는다(예측 반복은 하위 PREDICT 또는 별도 GPU step).
- **설치 스크립트는 관리자 권한 없이**: 머신 환경변수·관리자 확인을 쓰지 않는다. 비밀값은 런타임 파일(`<런타임>\secrets\`)에만, 작업 실행 인자에는 경로만(phase3 D3-41).

## 커밋 규칙

- 작은 단위로, 제목 한 줄(한국어 또는 영어, 72자 이내) + 필요 시 본문에 계약 절 번호(`platform.md §8.4`).
- 릴리스 시 `RELEASES.md` 최상단 항목과 루트 `pyproject.toml` `version`(= `physicsai_core.__version__`)을 같은 커밋에서 함께 올린다(`scripts/test-all`이 검사).
- 커밋 전 `scripts/test-all` 통과. 실패한 채로 커밋하지 않는다.
- 비밀값·`config/platform.yaml`·대용량 산출물(`*.psdata`, `*.psmdl`, `*.h3d`)을 커밋하지 않는다.
- 메인 에이전트가 지시하지 않으면 push하지 않는다.
