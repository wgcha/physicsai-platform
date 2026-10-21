# 릴리스 로드맵 — v0.2.4 · v0.2.5

작성: Plan, 2026-10-21. 기준: v0.2.3(b05d34d, migration HEAD `0019_extract_filter`). 확정 결정은 [decisions.md](decisions.md) 2026-10-21 줄.
원칙(사용자 확정 "v0.2.4에서 0.2.5까지 순차 적용"): **v0.2.4를 구현·검증·배포한 뒤 v0.2.5에 착수**한다. 버전 안에서는 아래 병렬 계획을 쓴다.

## 1. 버전별 범위

| 버전 | 범위 | 계약 | migration | 설정 키 | 상태 |
|---|---|---|---|---|---|
| v0.2.3 | Native 추출 조건(EF)·리브 위치·다중 사용 체크 | [extract-filter.md](contracts/extract-filter.md) | `0019_extract_filter` | – | 릴리스 완료 |
| **v0.2.4** | ① Native 템플릿 변수 선택·범위(④ 세트 정의·⑥·④ 일괄 그 자리 편집·실행 스냅숏) ② **MCP 기능 전체**(API 토큰 30일·공통 작업 계약 plan→confirm→run·감사·요약·x-mcp 생성기·용어집·호출 제한·**MCP 서버**(Streamable HTTP `/physicsai/mcp` + stdio `physicsai-mcp`)·연결 가이드, 클라이언트 Claude·Codex CLI·Gemini CLI) | [native-vars.md](contracts/native-vars.md), [mcp.md](contracts/mcp.md), [manual/mcp-clients.md](manual/mcp-clients.md) | `0020_mcp`(NV는 DB 무변경) | `mcp.*`(기본 `enabled: false`) | 계약 확정 |
| **v0.2.5** | ⑤·⑥ 업로드(브라우저 분할 업로드·경로 칸 두 탭) + HTML 결과 요약 보고서(⑤ 결과분석·등가성, ⑥ 내장·레거시) | [upload-report.md](contracts/upload-report.md) | `0021_uploads` | `storage.upload_root`, `upload.*`, `report.*` | 계약 확정, v0.2.4 배포 후 착수 |
| v0.2.6 이후 | 직접 최적화(`feat/r1-directopt` opt-direct, 계약만), 보고서 2차(④·①), PC 도구(h3d 축소 업로드, U3), ChatGPT 앱 커넥터용 OAuth(mcp §21.2), 유사 설계 검색(mcp Q2) | 각 계약 | HEAD 다음 번호 | – | 후속 |

## 2. 병합 순서·migration 체인

```text
EF(v0.2.3, 완료) ──▶ NV ─┐
                         ├─▶ [v0.2.4 릴리스·배포·현장 확인] ──▶ UP ─┐
                   MCP ──┘                                         ├─▶ [v0.2.5 릴리스]
                                                              RP ──┘
0019_extract_filter ──▶ 0020_mcp ──▶ 0021_uploads
```

- v0.2.4 안: NV·MCP 병렬 구현, **NV 먼저 병합**(작고 migration 없음) → MCP rebase(openapi·schema.d.ts·frontend-dist 재생성). NV의 새 operation은 x-mcp 표기를 NV 구현 커밋에 넣는다(native-vars §6.6 — MCP 병합 전에도 무해).
- v0.2.5 안: UP·RP 병렬 구현, **UP 먼저 병합**(migration 0021) → RP rebase. 둘 다 새 operation에 `x-mcp.exclude`(upload-report §4.1·§9.4) — V-MCP-6이 검사.
- migration 번호는 위 체인으로 확정(계약 "구현 시 HEAD 다음 번호" 원칙의 결과와 같음). 순서가 바뀌면 Plan에 먼저 알린다.

## 3. 브랜치·에이전트 분할(제안)

| 버전 | 브랜치(기준) | 에이전트 | 내용 | 병렬 |
|---|---|---|---|---|
| v0.2.4 | `feat/v024-nv-be`(v0.2.3) | impl-backend #1 | native-vars §9 Backend + §6.6 x-mcp | #2와 병렬 |
| | `feat/v024-mcp-be`(v0.2.3) | impl-backend #2 | mcp M1→M2→M3→M5 순차(같은 파일 공유), 옛 WIP `/home/claude/wt-mcp` 참고·현재 기준 재이식(mcp §16) | #1과 병렬 |
| | `feat/v024-fe`(NV-BE 병합 후) | impl-frontend 1명 | NV 화면 → MCP M4 "내 API 토큰" 순차(frontend-dist 충돌 회피) | BE openapi 갱신 뒤 |
| | `release/v0.2.4` | 메인 + verifier | NV → MCP-BE → FE 병합, V-NV·V-MCP 판정, RELEASES 0.2.4·pyproject 동시 갱신, 배포, e2e E7 | 순차 |
| v0.2.5 | `feat/v025-upload`(v0.2.4) | impl-backend #1 | BE-UP1(설정 `UploadCfg`·`ReportCfg` 둘 다 이 브랜치에서 추가) | #2와 병렬 |
| | `feat/v025-report`(v0.2.4) | impl-backend #2 | RP1→RP2→RP3 BE(설정 클래스는 UP 쪽 정의를 rebase로 받음) | #1과 병렬 |
| | `feat/v025-fe` | impl-frontend 1명 | FE-UP1 → FE-UP2 → 보고서 버튼 순차 | BE openapi 뒤 |
| | `release/v0.2.5` | 메인 + verifier | UP → RP → FE 병합, V-UP·V-RP·V-MCP-1·6 판정, 릴리스 | 순차 |

- 각 impl은 자기 브랜치에서 `scripts/test-all` 통과 후 커밋, push는 메인 지시 때만(AGENTS.md).

## 4. 충돌 파일

| 묶음 | 겹치는 파일 | 처리 |
|---|---|---|
| NV ↔ MCP | `backend/openapi.json`·`backend/tests/data/operation_ids.txt`·`frontend/src/api/schema.d.ts`(생성물), `frontend-dist/`(빌드본), `physicsai_api/main.py`(MCP 라우터·마운트만), mcp `SUMMARIES.param_set`(NV `vars_revision` 읽기) | 생성물은 rebase 후 재생성, FE 1명 순차. MCP `params_model`은 기존 요청 모델 재사용 → NV `vars` 자동 포함 |
| MCP 단독 | `deps.py`(인증 분기), `db/tables`, `config/schema.py`+`schema_mcp.py`, `config/platform.*.yaml`(추가만), `deploy/requirements.lock`·`collect-offline.*`·`caddy/physicsai.caddy`, `pyproject.toml` | 한 브랜치 순차(M1~M5) |
| UP ↔ RP | `config/schema.py`(Upload·Report Cfg), `config/platform.*.yaml`, `main.py` 라우터 등록, `openapi.json`, `deploy/caddy/physicsai.caddy`(주석) | UP가 설정 클래스 둘 다 추가, RP rebase |
| v0.2.5 ↔ v0.2.4 | `migrations`(0021 down_revision 0020), `requirements.lock`(python-multipart는 MCP 전이 의존 — UR-C1) | 순차 적용으로 해소 |

## 5. 버전별 검증 묶음

| 버전 | 자동(verifier) | 현장(e2e-checklist) |
|---|---|---|
| v0.2.4 | V-NV-1~10, V-MCP-1~20, V-SEC-1, 기존 전체 `scripts/test-all`(mcp 키 없는 설정 = 기존 동작, V-MCP-1) | E7-1~8(Claude Code·Codex CLI·Gemini CLI × HTTP·stdio, Vite·Caddy 경로), Native 변수 정의 편집 → ⑥·④ 일괄 실행 1회 |
| v0.2.5 | V-UP-1~15, V-RP-1~8, V-MCP-1·6(새 operation x-mcp exclude)·V-MCP-15 회귀 | V-UP-14(Caddy 16 MB 청크·30 GB h3d), V-RP-8(오프라인 브라우저 열기) |

## 6. 사용자 확인 대기

| # | 질문 | 차단 여부 | 회신 없을 때 |
|---|---|---|---|
| mcp Q4 | 사내 on-premise 배포 클라이언트(Claude·Codex·Gemini·사내 LLM)가 허용하는 전송(stdio 실행·사내 HTTP 주소 접속) | 아님 | 둘 다 제공 |
| mcp Q2 | 유사 설계 검색 도구 포함 | 아님 | 제외(후속) |
| mcp Q3 | `denied_job_kinds` 기본값 | 아님 | `[solve_pbs]` |
