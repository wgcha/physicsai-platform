# 릴리스 로드맵 — v0.2.7 · v0.2.8

작성: Plan, 2026-10-21(v0.2.4·v0.2.5) → **갱신 2026-10-22(v0.2.7·v0.2.8)**. 기준: 배포된 v0.2.6(5b965fe, migration HEAD `0021_uploads`, paicad 0.11.0). 확정 결정은 [decisions.md](decisions.md) 2026-10-22 줄.
원칙: 버전 순차 — **v0.2.7을 구현·검증·배포한 뒤 v0.2.8에 착수**. 버전 안에서는 아래 병렬 계획을 쓴다. 사용자 원칙 P1(데이터 생성 DOE와 최적화 DOE는 독립 변수 공간)·P2(최적화는 쿠션·조립 입력 구분)·P3(데이터 생성·학습은 조립만).

## 1. 버전별 범위

| 버전 | 범위 | 계약 | migration | 설정 키 | 상태 |
|---|---|---|---|---|---|
| v0.2.3 | Native 추출 조건·리브 위치 | [extract-filter.md](contracts/extract-filter.md) | `0019_extract_filter` | – | 릴리스 완료 |
| v0.2.4 | Native 변수 선택·범위 + MCP 기능 전체 | [native-vars.md](contracts/native-vars.md), [mcp.md](contracts/mcp.md) | `0020_mcp` | `mcp.*` | 릴리스 완료 |
| v0.2.5 | 업로드 + HTML 보고서 | [upload-report.md](contracts/upload-report.md) | `0021_uploads` | `storage.upload_root`, `upload.*`, `report.*` | 릴리스 완료 |
| v0.2.6 | 로컬 패키지 설치 빌드 격리 수정(이슈 #9) | – | – | – | **배포됨**(5b965fe) |
| **v0.2.7** | ① **예측 입력 종류(조립·쿠션)** 실행마다 선택(④ 단건·일괄, ⑥ 내장) — 쿠션 = 쿠션 rad 하나로 예측(GPU 메모리 초과 해소), Altair는 기존 mesh_only 경로 일원화, Native는 `paicad cushion write`(0.12.0), FEM 검증 쿠션 = 재조립(`assembly.kind: template`), Native 변수 출처 (b) ⑥ "새 Native 템플릿(STEP)" 링크 ② **P3 표시**(① "조립 기준", ③ 데이터셋 출처) ③ **웹 "AI 연결(MCP)" 페이지**(상태·토큰·4개 AI 도구 완성 설정 복사·도구 목록·연결 시험, `GET /mcp/connection`) | [input-kind.md](contracts/input-kind.md), [mcp.md](contracts/mcp.md) §23(MR-C3), [geometry-engine.md](contracts/geometry-engine.md) GE-C19 | **없음**(기존 `input_kind` 열·JSONB 재사용) | `commands.paicad_cushion_write`, `mcp.public_url`(기본 null) | 계약 확정, 착수 대기 |
| **v0.2.8** | **Altair 변수 공간**: ①-2 tpl 전체 파라미터 포함(사용 = DOE 범위, 미사용 = 공칭 고정, ① DOE 불변), ④ Altair 전체 tpl 템플릿 변수 정의(native-vars와 같은 API·리비전·스냅숏)·⑥·④ 그 자리 편집·학습 범위 경고, 옛 부분 tpl 편집 불가 + 재생성 안내, 기존 DOE는 from-train `tpl_source: current` | [altair-vars.md](contracts/altair-vars.md), native-vars NV-C3 | 없음 | – | 계약 확정, v0.2.7 배포 후 착수 |
| **v0.2.9(제안)** | **작업 대기열 분리**: GPU 1개씩(추론 구간만) · CPU 한도 안 병렬(기본 3) · step 구간별 슬롯 전환(T17) · 화면·`/queue` GPU/CPU 분리 | [job-queues.md](contracts/job-queues.md) | `0022_job_queues`(down `0021_uploads`) | `worker.queues.*` | 계약 초안 — 릴리스 배정 메인 확정 대기 |
| **v0.2.9** | **대기열 분리 + DOE 표본 방식 확장·지점 통일 + 조립 매칭**: DOE 방식([doe-methods.md](contracts/doe-methods.md): ①-3 Native 전 방식, Halton·균일 랜덤·① 표 CSV(학습 범위 밖 막음), ④·⑥ 다중 baseline 층화 생성기, ⑥ 탐색 방식 선택, Native 기본 lhs 유지) | doe-methods.md, 대기열 분리·조립 매칭 각 계약 | `0022_job_queues` → `0023_doe_methods` | – | 계약 확정, v0.2.8 배포 후 착수 |
| v0.2.10 이후 | 직접 최적화(opt-direct, 계약만), 보고서 2차(④·①), PC 도구(h3d 축소 업로드), ChatGPT 앱 커넥터용 OAuth, 유사 설계 검색(mcp Q2), 쿠션만으로 Native 템플릿(조립 폴더 없이, input-kind §7) | 각 계약 | HEAD 다음 번호(`0022_*`) | – | 후속 |

## 2. 병합 순서·migration 체인

```text
v0.2.6(배포) ──▶ v0.2.7: GEOM(paicad 0.12.0) ─┐
                         BE-IK1 ─────────────┼─▶ BE-IK2 ─▶ BE-MCP ─▶ FE ─▶ [v0.2.7 릴리스·배포·현장 V-IK-10]
                                             ┘
             ──▶ v0.2.8: BE-AV1(①) ─▶ BE-AV2(④·⑥) ─▶ FE ─▶ [v0.2.8 릴리스]
0021_uploads (v0.2.7·v0.2.8 migration 없음 — 필요해지면 0022_*를 Plan에 먼저 알림)
             ──▶ v0.2.9: 0022_job_queues(대기열 분리) ─▶ 0023_doe_methods(doe-methods, down_revision 0022_job_queues, predict_batches source_kind CHECK에 HALTON·RANDOM 추가) — 조립 매칭 등 그 밖 migration은 0024_*부터
```

- v0.2.7: paicad(Impl-Geom)·BE-IK1(API·조회)·BE-IK2(워커)는 병렬 구현, 병합은 GEOM → IK1 → IK2(fake_paicad `cushion write`는 IK2가 계약대로 만들어 GEOM 병합 전에도 시험 가능) → MCP 페이지 BE(작음 — `config/schema_mcp.py`·`routers/mcp.py`) → FE 1명(입력 종류 화면 → AI 연결 페이지 순차, `frontend-dist` 충돌 회피). `openapi.json`·`schema.d.ts`는 병합마다 재생성.
- v0.2.8: AV1(`train_tpl`·① DOE)이 `fill_nominal`을 만들고 AV2가 그 위에서(같은 브랜치 순차 권장 — `native_vars.py`·워커 렌더 공유).

## 3. 브랜치·에이전트 분할(제안)

| 버전 | 브랜치(기준) | 에이전트 | 내용 | 병렬 |
|---|---|---|---|---|
| v0.2.7 | `feat/v027-paicad-cushion`(v0.2.6) | impl-geom | input-kind §5(`cushion write`, 0.12.0·CHANGELOG·시험) | 전부 병렬 |
| | `feat/v027-ik-api`(v0.2.6) | impl-backend #1 | input-kind §11 BE#1(요청 `input`·능력·조회·FEM `template`·③ 출처·MCP 요약) | |
| | `feat/v027-ik-worker`(v0.2.6) | impl-backend #2 | input-kind §11 BE#2(Native 쿠션 체인·설정 키·fake_paicad·`predict_input`) | |
| | `feat/v027-mcp-page`(IK 병합 후 또는 병렬) | impl-backend #1(이어서) | mcp §23.5 BE(`mcp.public_url`·`GET /mcp/connection`) | 작음 — IK1 뒤 순차 |
| | `feat/v027-fe` | impl-frontend 1명 | 입력 종류(배지·선택·열·①·③·⑥ 링크) → AI 연결(MCP) 페이지 | BE openapi 뒤 |
| | `release/v0.2.7` | 메인 + verifier | 병합·V-IK-1~10·V-MCP-21~26·V-GE(paicad), RELEASES 0.2.7·pyproject 동시, 배포, 현장 V-IK-10 | 순차 |
| v0.2.8 | `feat/v028-altair-vars`(v0.2.7) | impl-backend 1명 | altair-vars §8 #1 → #2 순차 | – |
| | `feat/v028-fe` | impl-frontend | altair-vars §7 | BE openapi 뒤 |
| | `release/v0.2.8` | 메인 + verifier | V-AV-1~8, 현장 ① DOE 불변 1회(R1) | 순차 |

- 각 impl은 자기 브랜치에서 `scripts/test-all` 통과 후 커밋, push는 메인 지시 때만(AGENTS.md).

## 4. 충돌 파일

| 묶음 | 겹치는 파일 | 처리 |
|---|---|---|
| IK1 ↔ IK2 | `physicsai_core/stage4_predict/input_kind.py`(IK1 소유, IK2는 읽기), `job_types.py`(IK2 `step_label`만) | IK1 먼저 병합, IK2 rebase |
| IK ↔ MCP 페이지 | `backend/openapi.json`·`operation_ids.txt`·`schema.d.ts`(생성물), `config/schema*`·`platform.example.yaml`(추가만) | 생성물 재생성, FE 1명 순차 |
| IK2 ↔ paicad | CLI 인자·`cushion.json` 키(계약 고정) | 계약 변경은 Plan 경유(GE-C19) |
| v0.2.8 ↔ v0.2.7 | `native_vars.py`·`surrogate_opt_problem.py`·`job_params/stage4_batch.py`·워커 `predict.py`·`batch.py` | 순차 적용으로 해소 |

## 5. 버전별 검증 묶음

| 버전 | 자동(verifier) | 현장(e2e-checklist) |
|---|---|---|
| v0.2.7 | V-IK-1~10, V-MCP-21~26(+V-MCP-1·6 회귀), paicad 시험(V-IK-5), 기존 전체 `scripts/test-all` | ⑥ 쿠션 입력 1회 GPU 메모리 초과 없음, Native 쿠션 rad로 edspy 예측 성공(input-kind R1), AI 연결 페이지에서 4개 도구 중 1개 이상 복사 설정으로 연결·`ping` |
| v0.2.8 | V-AV-1~8, V-NV 회귀 | ① DOE 같은 값 run 형상 동일(노드 수·부피, altair-vars R1) |

## 6. 후속 항목(버전 미배정)

| 항목 | 내용 | 근거 |
|---|---|---|
| ④ 단건 "학습 범위 밖" 기준 | 단건도 모델 학습 범위 기준으로(현재 세트 범위) | native-vars R5 |
| 쿠션만으로 Native 템플릿 | 조립 폴더 없이 쿠션 STEP + 쿠션 메시로 Native 등록 | input-kind §7 |
| (종결) MCP 활성 관리자 안내 | v0.2.7 mcp §23.1 관리 화면 한 줄로 반영 | MR-C3 |

## 7. 사용자 확인 대기

| # | 질문 | 차단 여부 | 회신 없을 때 |
|---|---|---|---|
| input-kind Q1 | 쿠션 실행의 FEM 검증: 재조립 허용(계약 기본) vs 비활성 | 아님 | 재조립 허용 |
| input-kind Q2 | ⑥ 쿠션 입력에서 쓰는 목적·제약 응답이 쿠션 부품 기준인지 | 아님 | 경고만(`INPUT_CUSHION_RESPONSES`) |
| mcp Q4 | 사내 배포 클라이언트가 허용하는 전송(stdio·사내 HTTP) | 아님 | 둘 다 제공 |
| mcp Q2 | 유사 설계 검색 도구 포함 | 아님 | 제외(후속) |
| mcp Q3 | `denied_job_kinds` 기본값 | 아님 | `[solve_pbs]` |
