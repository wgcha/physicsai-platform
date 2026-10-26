# 계약: DOE 표본 형상 그리드 미리보기 (doe-preview, DP-C*)

작성: Plan, 2026-10-26(초안) → **확정 2026-10-26**(Q1 사용자, Q2·Q3 메인 기본 = 권고안). 요구(원문): "형상 파라미터 변수를 샘플링으로 doe만들면 그리드 구조로 변화된 형상 미리보기가 보여줬으면해."
기준: v0.2.10 배포본 fb644a1(migration HEAD `0024_contour3d_field`, paicad 0.13.0). 결정 번호 `DP-C*`, 검사 `V-DP-*`.
상위 계약(이 문서가 다시 쓰지 않는 규칙은 그대로): [geometry-view.md](geometry-view.md)(이하 **GV** — `paicad view preview`·GLB·`_DISP_MM`·서버측 캐시·housekeeping·뷰어), [geometry-engine.md](geometry-engine.md)(**GE** — §7.3.3 ①-3 Native DOE, §7.3.6 run 레이아웃, `render.py` 피처 PNG), [shell-morph.md](shell-morph.md)(**SM**), [doe-methods.md](doe-methods.md)(**DM** — `SITE_KINDS`·표본 행 생성), [job-queues.md](job-queues.md)(**JQ** — CPU 대기열), [mcp.md](mcp.md)(x-mcp·JOB_KINDS).
릴리스(확정): **v0.2.11**. migration `0025_doe_preview` 1개(down_revision `0024_contour3d_field`). paicad **0.14.0**(새 하위 명령 `view grid`·`shell view grid`, 기존 명령 불변) — 같은 버전의 리브 간격(rib-gap.md, migration 없음)의 `RIB_GAP`과 **같은 paicad 0.14.0**에 함께 들어간다(roadmap v0.2.11).

## 0. 한 줄 요약

①-3 Native DOE 카드에서 표본 방식·run 수를 정한 뒤 **[형상 미리보기]**를 누르면, 워커가 표본 표를 실제 DOE와 **같은 함수로** 계산하고, 표본 24개(공칭 1 + 변화가 큰 순 23)를 `paicad view grid`(update만, 한 프로세스에서 여러 표본)로 갱신해 **표본마다 같은 카메라·같은 축척·같은 색 범위의 썸네일 PNG**(서버 소프트웨어 래스터라이저 — GPU·WebGL 불필요)와 GLB를 만든다. 화면은 PNG 격자(6열)를 보여 주고, 셀을 누르면 기존 3D 뷰어(WebGL 컨텍스트 1개)로 그 표본을 연다. 생성이 끝난 DOE에는 같은 격자를 "형상 갤러리"로 열고 실제 생성 결과(스킵 코드)를 겹쳐 보인다. Altair 경로는 제외한다.

---

## 1. 조사 결과

| 항목 | 현재 | 이 기능에 쓰는 점 |
|---|---|---|
| DOE 생성 지점 | ①-3 Native(`DoeGenCard.NativeFields` → `TD_DOE_GEN` native, 표본 행은 워커 DG_PREP에서 `lhs_values`/`doe_platform.build`/층화), ①-3 Altair 플랫폼·HyperStudy, ④ 일괄(`build_matrix`), ⑥ 탐색 새 DOE(`_explore_batch`) — DM §1·§3 | 표본 행은 **워커에서** 결정적으로 계산된다(`lhs_opt`는 수십 초 가능, DM R2). API는 검증만 한다 → 미리보기 작업 안에서 같은 함수로 행을 다시 계산 |
| 단건 형상 미리보기 | GV `paicad view preview`(update만 = 수 초, `fe=check` = morph+check), `GEOM_PREVIEW`(레인 PREVIEW, 동시 1, ④ 세트 전용), 캐시 `<study>/_cache/geom_preview/`(7일·2 GiB 합산), 뷰어 three.js(공칭 반투명 + 변경 형상 `_DISP_MM` 색) | 표본 1개 처리 의미(update·테셀레이션·`_DISP_MM`·실패 코드)를 그대로 재사용. 레인 PREVIEW는 단건용(동시 1)이라 격자 작업이 막으면 안 됨 |
| 서버 PNG 렌더 | `paicad/render.py` = numpy+zlib **소프트웨어 래스터라이저**(OpenGL 없음 — OCP VTK는 헤드리스에서 프로세스를 죽이므로 배제됨), 800×600 고정 상수, 정사영 등각, 면 단위 색 | 폐쇄망·GPU 없는 서버에서 바로 동작. 크기·카메라·정점 색(변위) 인자화만 필요 |
| ①-3 Native run 산출물 | run 평탄 레이아웃 `R/_paicad/{values.json, update/, morph/, check/}`, 실패 시 `R/SKIPPED.json{code, category, step}`(GE §7.3.6) | 생성 후 갤러리에서 실제 생성 결과(스킵 코드·단계) 겹쳐 표시 |
| ① run 표(RunTable) 3D | 결과 h3d **컨투어** 3D(`ContourPanel`, SOLVER_H3D)만 — 형상 보기 없음 | 형상 갤러리와 별개(변경 없음) |
| Altair 경로 | 형상 갱신 = NX 식 갱신 + SimLab(라이선스·분 단위/표본), paicad·B-rep 없음 | 미리보기 비용이 실제 DOE 생성과 같아 의미 없음 → 제외(DP-C10) |
| ①-1 기반 Native DOE | 세트 없음, tag는 DOE 실행 때(HST_GEN_RADIOSS ①) 생성. update는 `--tag-dir` 없이도 동작(GV §5.1 선택 인자) | 생성 전에는 tag 없이 update → 기준면이 실제 생성과 다를 수 있음(R3, 화면 표시) |

## 2. 결정(DP-C*)

| # | 결정 | 근거 |
|---|---|---|
| DP-C1 | **시점 = 생성 전 미리보기(1순위) + 생성 후 갤러리(2순위), 한 메커니즘**. 둘 다 "표본 행 목록 → 셀 렌더"이며 생성 후는 `doe_matrix.csv`를 행 출처로 쓰고 실제 생성 결과를 겹친다 | 사용자 요구의 가치는 몇 시간짜리 생성 전에 이상 표본(충돌·과대 변형)을 보는 데 있음. 생성 후는 같은 코드·캐시로 거의 공짜 |
| DP-C2 | **렌더 = (c) 혼합**: 격자는 서버 썸네일 PNG, 셀 클릭 시 그 표본 하나만 기존 3D 뷰어로. (a) 단독·(b) 기각(§4) | WebGL 컨텍스트 상한(브라우저당 보통 8~16)·GLB 24개 동시 적재 메모리·원격 데스크톱 소프트웨어 GL(GV R2)을 모두 피함. 서버 PNG는 기존 래스터라이저 재사용 |
| DP-C3 | **표본 수 규칙**: 한 페이지 = `page_size`(기본 24, 6×4) 셀, 첫 셀은 항상 **공칭**(기준). 기본 정렬 "변화 큰 순"(정규화 거리 내림차순) + [DOE 순서]·[변수 값↑↓] 전환, [다음 24개]로 페이지 추가. 전체 일괄 버튼 없음. **확정(Q2, 메인 기본 = 권고안)** | 수백 표본 전부는 수 분~수십 분(§6.4). 변화 큰 순이 충돌·과대 변형을 먼저 보여 줌 |
| DP-C4 | **공통 카메라·축척·색 범위**: 카메라 = 공칭 B-rep bbox 기준 정사영(방향·여백 설정값), 색 범위 = `[0, disp_ref_mm]`(세트 범위에서 미리 계산, §3.3). 모든 셀·모든 페이지가 같다 | 셀끼리 비교 가능 + 셀 단위 캐시 가능(다른 셀 결과를 기다리지 않음) |
| DP-C5 | **paicad 새 명령 `paicad view grid`·`paicad shell view grid`**: 한 프로세스에서 표본 여러 개를 update → 테셀레이션 → GLB·manifest·썸네일. 셀 산출물은 `view preview --fe off`와 같은 GLB·manifest + `thumb.png`. 기존 명령 불변 | OCP 적재(1~2 s)를 표본마다 반복하지 않음. 단건 미리보기와 결과 동일성 검사 가능(V-DP-2) |
| DP-C6 | **새 job_type `DOE_PREVIEW`, CPU 대기열**(JobTypeDef 레인 SLOT, LOCAL step `res=cpu`). PREVIEW 레인은 쓰지 않는다. **확정(Q3, 메인 기본 = 권고안)** | 24셀 ≈ 1분 — 동시 1인 PREVIEW 레인을 막으면 ④ 단건 미리보기가 밀림. JQ 규칙(새 LOCAL step `res` 필수) 준수 |
| DP-C7 | **캐시 = 셀 단위**, 키 = 행 출처와 무관한 형상 입력(CAD·features·tag·options·값·테셀레이션·썸네일 옵션·paicad 버전). 위치 `<study>/_cache/doe_preview/`, GV §6.6 housekeeping·보관 7일·총량 합산 그대로 | 정렬·페이지·생성 전/후가 바뀌어도 같은 표본은 재계산 없음 |
| DP-C8 | **표본 행 = 실제 DOE와 같은 함수·같은 입력**(DM: `lhs` → `lhs_values`, 그 밖 → `doe_platform.build`, `table`·`train_doe` 그대로). 요청 본문은 `TD_DOE_GEN` native params의 표본 부분과 같은 모양 | 미리보기와 실제 생성 표본이 어긋나면 기능이 무의미. V-DP-3이 바이트 동일 검사 |
| DP-C9 | **update만**(morph·check 없음). 셀 상태 = update 결과(OK/FAIL 코드). 생성 후 갤러리는 실제 morph·check 결과를 별도 배지로 겹침 | morph+check는 표본당 수십 초(GV GV-4) — 격자 규모에 부적합. 품질 실패(`GEOM_QUALITY`)는 생성 후에만 보임을 화면에 명시 |
| DP-C10 | **범위**: 1차 = ①-3 Native **단일 baseline**(①-1 기반·세트 기반) 생성 전 + ①-3 Native DOE 생성 후 갤러리. 다중 baseline·④ 일괄·⑥ 탐색·Altair는 1차 제외(④ Native 단일 baseline은 같은 API에 `site:"batch"`만 더하면 되는 후속 1순위). **확정(Q1, 사용자)** | 사용자 요구 지점(DOE 만들 때)에 집중. 다중 baseline은 baseline마다 CAD·카메라가 달라 공통 축척 규칙이 따로 필요. Altair는 DP-C2 근거 없음(비용) |
| DP-C11 | **UI 원칙**: DOE 카드에 버튼 1개, 격자 패널은 카드 바로 아래 전폭 카드 1개(툴바 1줄 + 범례 + 격자). 라이트 테마, 2560×1440 기준 6열 | 사용자 원칙(필수 UI만) |

## 3. 셀(표본 1개) 산출물 계약 — `paicad view grid`

### 3.1 CLI(GV §5 공통 규약: 인자 두 토큰, `--out-dir`에만 쓰기, `PAICAD PROGRESS`/`PAICAD RESULT`, `paicad.log`, `--threads`)

| 명령 | 인자(필수 **굵게**) | 출력 |
|---|---|---|
| `paicad view grid` | **`--cad`**, **`--features`**, **`--cells`**(`cells.json`, §3.2), **`--out-dir`**, `--tag-dir`, `--body-map`, `--options`, `--view-options`(GV §4.5), **`--thumb-options`**(§3.3) | `grid_manifest.json`(존재 = 성공 판정) + 셀마다 `cells/<cell_id>/{preview_manifest.json, preview.glb?, thumb.png}` |
| `paicad shell view grid` | **`--cad`**, **`--features`**, **`--cells`**, **`--out-dir`**, **`--fixed-dir`**, `--tag-dir`, `--body-map`, `--options`, `--view-options`, **`--thumb-options`** | 위와 같음(`kind:"shell"`) |

- 처리: CAD·features 적재 1회 → 공칭 bbox·카메라 계산 1회 → 셀마다(입력 순서) update → (OK면) 테셀레이션·`_DISP_MM`·GLB·manifest → 썸네일. **셀 하나의 실패는 다음 셀을 막지 않는다**. 셀 폴더는 임시 이름으로 쓴 뒤 rename(완료 셀만 보임).
- 셀의 `preview_manifest.json`·`preview.glb`는 같은 입력의 `paicad view preview --fe off` 출력과 **바이트 동일**(`timing` 제외, GV §5.2-5). `reports.update`는 셀 폴더 `update/` 기존 형식. include·`morphed.inc`·`files/` 쓰지 않음(GV V-GV-7).
- 종료코드: 0 = 모든 셀 처리(셀별 OK/FAIL 무관), 3 = 입력 오류(`cells.json` 모르는 이름·비유한 값·중복 id), 14 = 공칭 테셀레이션 실패(셀 처리 전), 20 = 내부 오류. 셀별 `VIEW_*`는 그 셀 manifest에 기록하고 계속.
- 결정성: 같은 입력·옵션·버전이면 셀 GLB·manifest(`timing` 제외)·`thumb.png` 바이트 동일.

### 3.2 `cells.json`(플랫폼 작성)

```json
{"schema_version": 1,
 "cells": [{"id": "9f2c…", "values": {"CUSH_L_THK_1": 12.9, "HOLE_R_1": 4.2}},
           {"id": "nominal", "values": {}}]}
```
- `id` = 플랫폼 셀 캐시 키(§6.3) 또는 `nominal`, `[0-9a-z_]{1,64}`. `values` 빠진 이름 = 공칭(GE §4.4와 같음).

### 3.3 `thumb_options.json`(플랫폼 작성 = 설정 `doe_preview.thumb` 사용값 + 계산값)

```json
{"schema_version": 1, "w": 320, "h": 240, "view_dir": [1, -1, 1], "margin": 1.15,
 "disp_range_mm": [0.0, 2.5], "colormap": "turbo16", "nominal_ghost": true, "edges": false}
```

| 키 | 규칙 |
|---|---|
| `w`·`h` | 160~800, 기본 320×240(2560 폭 6열 셀에 1:1) |
| `view_dir` | 장면→시점 방향(정규화 전), 기본 등각 `[1,-1,1]`, up = Z(GV §4.1). 모든 셀 공통 |
| `margin` | 1.0~2.0. 정사영 축척 = 공칭 B-rep bbox(바디 전부) 투영 크기 × `margin`이 화면에 맞도록. **중심·축척은 공칭으로만 정한다**(셀 형상과 무관) |
| `disp_range_mm` | 색 범위. 플랫폼 계산: `disp_ref_mm = max over 사용 파라미터 of max(|max−nominal|, |nominal−min|)`(길이 단위 파라미터만, 각도·무차원 제외, 0이면 1.0). 범위 밖은 끝 색으로 포화 |
| `colormap` | `turbo16`(16단계 고정 표, paicad 상수 — 뷰어 범례와 같은 표) |
| `nominal_ghost` | true면 공칭 외곽(엣지 선, 연회색 1 px)을 먼저 그림 — 변화 방향을 한눈에 |

- 그림: 배경 흰색, 셀 형상 = 정점 `_DISP_MM` → 색표, 음영 = 기존 `_shade`. update FAIL 셀은 **공칭 회색 + `failure.features` 면 빨강**(형상 GLB 없음). 셀 형상이 화면 밖으로 나가면 manifest `thumb.clipped: true`(그림은 잘린 채).
- `render.py`의 800×600 상수·면 단위 색을 인자(`w`,`h`,정점 색)로 일반화한다. 기존 extract 피처 PNG 출력은 바이트 불변(V-DP-1).

### 3.4 셀 manifest 추가 키 / `grid_manifest.json`

- 셀 `preview_manifest.json`(GV §4.3 그대로) + 최상위 `thumb: {file:"thumb.png", sha256, w, h, clipped}`(선택 키 — `view preview`에는 없음, 바이트 동일 비교는 이 키를 제외).
- `grid_manifest.json`: `{schema_version, kind, engine_version, camera:{view_dir, center, scale, digest}, disp_range_mm, nominal:{bbox, view_sha256}, cells:[{id, status:"OK"|"FAIL"|"ERROR", code, category, max_disp_mm, total_s}], timing:{load_s, total_s}}`. `ERROR` = 셀 처리 중 `VIEW_*`·내부 예외(재시도 대상, 캐시 안 함).

## 4. 렌더 방식 비교(DP-C2 근거)

| 방식 | 장점 | 단점 | 판정 |
|---|---|---|---|
| (a) 서버 PNG 격자만 | 가벼움(셀 ≈ 20~60 KB), WebGL 불필요, 원격 데스크톱·구형 PC 무관, 서버는 기존 소프트웨어 래스터라이저(헤드리스 안전) | 회전·확대 불가 | 격자 표시에 채택 |
| (b) 브라우저 한 three 장면 + 뷰포트 분할(scissor) | 컨텍스트 1개로 상한 회피, 시점 동기 회전 | GLB 24개(각 0.8~16 MB) 동시 적재 → 수십~수백 MB 전송·GPU 메모리, 소프트웨어 GL에서 수 fps, 페이지마다 재적재. 셀별 `<canvas>`면 컨텍스트 상한(8~16)에 바로 걸림 | 기각 |
| (c) 혼합: 격자 PNG + 클릭 시 3D 1개 | (a)의 가벼움 + 필요할 때 기존 뷰어(공칭 반투명 겹침·변위 색·실패 빨강, GV §7.3)의 상호작용 | 셀 GLB 디스크(캐시 총량에 합산) | **권고** |

서버 오프스크린: OpenGL·VTK 경로는 쓰지 않는다(render.py 머리말 근거 — 헤드리스에서 프로세스 중단). 래스터는 numpy 일괄 연산(`_raster`), 320×240이면 셀당 0.2~1 s 예상(삼각형 수 비례, V-DP-11 측정).

## 5. 행 출처·선택

### 5.1 출처(`source`)

| `source.kind` | 지점 | 형상 입력 | 표본 행 |
|---|---|---|---|
| `train` | ①-3 Native, ①-1 Native 추출 기반(세트 없음) | `01_train/cad/…`(+body_map), `features_rel`, tag **없음**, options = 유효 기본값(GE §7.3.3 DG_PREP ②와 같음) | 요청 `sampling`으로 DM 함수 계산(DP-C8) |
| `param_set` | ①-3 Native, 세트 기준(단일 baseline) | `S/native/{extract,tag}`, 세트 유효 geom options, 쉘이면 `S/native/fixed` | 같음 |
| `train_doe` | 생성 후 갤러리(①-3 Native DOE, HST_GEN_RADIOSS 이후) | `D/cad/`, `D/native/extract/`, `D/native/tag/`, `D/native/options.json` | `D/doe_matrix.csv` 그대로 + run별 생성 결과(`R/SKIPPED.json` 유무·code·step) |

- 다중 baseline 세트·`train_native_multi` → 409 `DOE_PREVIEW_UNSUPPORTED`("다중 baseline DOE는 형상 미리보기를 지원하지 않습니다"). Altair 템플릿·`engine≠native` → 409 같은 코드("형상 미리보기는 Native 형상 엔진에서만 쓸 수 있습니다").
- `train`은 tag가 없어 기준면 규칙이 실제 생성과 다를 수 있다 → 응답 `tag_state:"none"`, 화면 안내(§8). `train_doe`에서는 tag가 있으므로 같은 표본이라도 셀 키가 다를 수 있다(정상).

### 5.2 선택(`select`) — 페이지

- `order`: `change`(기본) = 사용 파라미터마다 `(v − nominal)/(max−min)`의 L2 노름 내림차순(같으면 doe_no 오름차순) · `doe` = doe_no 오름차순 · `var` = `var` 값 오름(`desc:true`면 내림, 같으면 doe_no).
- `offset`(0, `page_size` 배수)·`limit`(= `page_size`, 최대 `doe_preview.max_page_size`). 첫 페이지(offset 0)는 공칭 셀 + 표본 `limit−1`개, 이후 페이지는 표본 `limit`개.
- 정렬은 **전체 표본 표 기준**(값은 렌더 없이 알 수 있음)으로 다음에 렌더할 표본을 정한다. "실패만" 필터는 **이미 렌더된 셀**에만 적용(전체 실패 검사는 비범위 — 후속 후보).

## 6. 플랫폼

### 6.1 작업 `DOE_PREVIEW`

`JOB_TYPES["DOE_PREVIEW"] = JobTypeDef("DOE_PREVIEW", 1, "SLOT", "형상 미리보기(DOE)", (DP_PREP INTERNAL 5, DP_MATRIX INTERNAL 10, DP_RENDER LOCAL res=cpu 80, DP_REGISTER INTERNAL 5), "①", notify_success=False)`, `can_retry=false`, 알림 없음, 작업 목록 기본 숨김(GV §6.4와 같은 "미리보기 포함" 필터), `ux_jobs_study_type_active` 제외.

| step | 처리 |
|---|---|
| DP_PREP | 입력 재확인(세트 READY·STALE이면 `GEOM_PREP_STALE`, `features_rel` 존재), 작업 폴더 `T = <study>/_cache/doe_preview/jobs/<job_id>/` |
| DP_MATRIX | 행 계산(§5.1). 행렬 캐시 `M = _cache/doe_preview/matrix/<mkey>/doe_matrix.csv`(`mkey` = sha256(정규 JSON{source 형상 입력 digest, 정규화 sampling, 사용 이름·범위})) — 있으면 재사용. `train_doe`는 `D/doe_matrix.csv` 사본. 선택 규칙(§5.2)으로 이번 페이지 표본 결정 → 셀 키 계산 → 캐시 DONE 셀 제외 → `T/cells.json`(남은 셀만), `T/thumb_options.json`, `T/view_options.json` |
| DP_RENDER | 남은 셀을 `chunk_cells`(기본 4)씩 묶어 `ctx.run_parallel`(최대 `parallel`, 기본 2)로 `paicad_view_grid`/`paicad_shell_view_grid` 실행(`--threads 1`, `{out_dir}` = `T/chunk_<i>`). 청크 하나가 끝날 때마다 완료 셀을 셀 캐시 폴더로 이동·artifacts 등록·`doe_preview_cells` 갱신(화면 폴링이 바로 채움). 시간 한도 = 청크 셀 수 × `timeout_s_per_cell` |
| DP_REGISTER | `doe_previews` 요약(`n_ok`·`n_fail`·`n_error`·`timing`) 기록 |

- 셀 판정(GV-10 규칙 준용): 셀 `status OK|FAIL` → 캐시 DONE(같은 입력 = 같은 결과). `ERROR`·청크 시간 초과·manifest 없음 → 그 셀만 `ERROR`(캐시 안 함), 작업은 SUCCEEDED + 경고 `DOE_PREVIEW_PARTIAL`. 모든 셀 ERROR면 작업 FAILED(첫 코드).
- 취소: `POST /doe-previews/{id}/cancel`(요청자·관리자) → 작업 취소 플래그(T8). 완료 청크 셀은 캐시에 남는다.
- MCP: `DOE_PREVIEW`는 `JOB_KINDS` 제외(사유 "화면 전용 형상 그림 생성"), 새 API는 `x-mcp.exclude`(같은 사유). 결과 엔티티 `SUMMARIES` 등록 없음.

### 6.2 시간 추정(1차 목표 — V-DP-11로 측정·기록)

| 항목 | 가상 쿠션(개발 PC) | 실물(현장 회신) |
|---|---|---|
| 청크 시작(OCP·CAD 적재) | 1~2 s | 2~5 s |
| 셀 1개(update + 테셀레이션 + GLB + 썸네일) | 2~3 s | 3~10 s |
| 24셀, `parallel` 2, `chunk_cells` 4 | ≈ 40~60 s, **목표 ≤ 90 s** | 1~3분 |
| 다음 페이지(행렬 캐시 적중) | 위와 같음(셀만) | — |

### 6.3 셀 캐시

- 셀 키 = sha256(정규 JSON — 키 정렬·공백 없음·float `repr(float(v))`): `{kind, shape_digest, values(사용 파라미터 전부, 빠진 값 공칭), view_tess, thumb_digest, engine_version}`.
  - `shape_digest` = CAD sha256들 + body_map sha + `features` sha + tag 폴더 digest(없으면 `null`) + 유효 geom options sha + (쉘) `fixed_digest`. 출처(`train`·`param_set`·`train_doe`)는 키에 넣지 않는다(DP-C7).
  - `thumb_digest` = sha256(`thumb_options.json` 정규 JSON — `disp_range_mm`·카메라 포함).
  - `engine_version` 모르면 캐시 조회 없이 전부 렌더(GV §6.4).
- 폴더 `<study>/_cache/doe_preview/cells/<key[0:2]>/<key>/`. housekeeping = GV §6.6 그대로(대상에 `_cache/doe_preview/` 추가, 보관 기간·총량 `geometry.view.cache` 합산, 링크·경로 탈출 거부, `doe_preview_cells.status = EXPIRED`·artifacts 삭제·410). `jobs/<job_id>/`·`matrix/`도 같은 기간 규칙.

### 6.4 동시·중복

1. 같은 `grid_key`(= sha256{source digest, mkey, select}) QUEUED·RUNNING → 그 미리보기 반환(작업 중복 없음).
2. 모든 셀이 DONE → 작업 없이 200(`cache_hit:true`, 셀 `last_access_at` 갱신).
3. 같은 사용자·같은 출처의 이전 QUEUED 미리보기는 취소(최신 우선, GV §6.4-3). RUNNING은 둔다.
4. 사용자별 QUEUED+RUNNING `DOE_PREVIEW` ≥ `max_active_per_user`(기본 2) → 429 `PREVIEW_BUSY`(기존 코드·문구).
5. 정리 작업 중 409·보관 Study 409 그대로. CPU 대기열 대기·순서 이동은 JQ 규칙 그대로(대기 중이면 화면에 "CPU 대기열 n번째").

### 6.5 설정(`config/platform.example.yaml`)

```yaml
doe_preview:                     # 절이 없으면 아래 기본값
  enabled: true                  # features.doe_preview = enabled + paicad_view_grid 비null + 실행 파일 존재
  page_size: 24                  # 6~48
  max_page_size: 48
  chunk_cells: 4                 # 1~16
  parallel: 2                    # 1~4 (CPU 슬롯 1개 안에서 프로세스 수)
  timeout_s_per_cell: 60
  max_active_per_user: 2
  thumb: {w: 320, h: 240, view_dir: [1, -1, 1], margin: 1.15, colormap: turbo16, nominal_ghost: true}
commands:
  paicad_view_grid: ["{paicad}", "view", "grid", "--cad", "{cad_input}", "--features", "{features_json}", "--cells", "{cells_json}", "--tag-dir", "{tag_dir}", "--options", "{options_json}", "--view-options", "{view_options_json}", "--thumb-options", "{thumb_options_json}", "--threads", "{threads}", "--out-dir", "{out_dir}"]
  paicad_shell_view_grid: ["{paicad}", "shell", "view", "grid", "--cad", "{cad_input}", "--features", "{features_json}", "--cells", "{cells_json}", "--fixed-dir", "{fixed_dir}", "--tag-dir", "{tag_dir}", "--options", "{options_json}", "--view-options", "{view_options_json}", "--thumb-options", "{thumb_options_json}", "--threads", "{threads}", "--out-dir", "{out_dir}"]
```
- `TEMPLATE_SPECS`: 두 키 `required=False`, argv[0] `{paicad}`. 새 placeholder `cells_json`·`thumb_options_json`. `{tag_dir}`는 선택 쌍(`train` 출처는 `"--tag-dir","{tag_dir}"` 쌍 생략 — GV `{renum_csv}` 방식), `{body_map}`은 argv 끝(GE §7.1).

### 6.6 API(`backend/openapi.json` — Backend)

| 메서드·경로 | 권한 | 요청 | 응답 | 오류 |
|---|---|---|---|---|
| `POST /studies/{id}/doe-previews` | power + CSRF | `DoePreviewReq` | 200 `DoePreview`(전부 캐시) \| 202 `DoePreview`(`job_id`) | 409 `DOE_PREVIEW_UNSUPPORTED`·`GEOM_PREP_STALE`·`DOE_PREVIEW_UNAVAILABLE`(`features.doe_preview=false`)·`STUDY_CLEANUP_RUNNING`, 422 `DOE_SAMPLING_INVALID`(DM과 같은 검증·problems), 429 `PREVIEW_BUSY` |
| `GET /doe-previews/{id}` | 로그인(Study 읽기) | – | `DoePreview` | 404 |
| `POST /doe-previews/{id}/cancel` | 요청자(power)·관리자 + CSRF | – | 202 `DoePreview`(asm-match 취소 선례, 감사 `DOE_PREVIEW_CANCEL`) | 404, 409 `JOB_TERMINAL` |
| `GET /artifacts/{id}/media`·`/content` | 기존 | – | PNG(`image/png`)·GLB·manifest | 404, 410 `ARTIFACT_EXPIRED` |

```jsonc
// DoePreviewReq — sampling 부분은 TD_DOE_GEN native params와 같은 키(DM §5.1: sampling | num_runs+seed, param_set_id, names)
{"source": {"kind": "train|param_set|train_doe", "param_set_id": null, "doe_id": null},
 "sampling": {"kind": "lhs", "count": 120, "seed": 1},          // train_doe면 생략(무시)
 "select": {"order": "change|doe|var", "var": null, "desc": false, "offset": 0, "limit": 24}}
// DoePreview
{"id": "dp1", "job_id": "j1", "status": "QUEUED|RUNNING|DONE|FAILED|CANCELED", "cache_hit": false,
 "queue": {"lane": "CPU", "position": 2},                         // 대기 중일 때만
 "n_total": 120, "order": [0, 57, 13, "…"],                       // 정렬된 전체 doe_no(행렬 계산 후, ≤ 2000개 정수)
 "tag_state": "none|tagged", "disp_range_mm": [0, 2.5], "colormap": "turbo16",
 "cells": [{"doe_no": null, "nominal": true, "status": "PENDING|OK|FAIL|ERROR", "values": {"…": 0},
            "top_changes": [{"name": "CUSH_L_THK_1", "value": 13.1, "rel": 0.05}],   // |rel| 큰 순 3개(rel = (v−nom)/(max−min))
            "code": null, "category": null, "message_ko": null, "max_disp_mm": 0.0, "clipped": false,
            "png_artifact_id": "a1", "glb_artifact_id": "a2", "manifest_artifact_id": "a3",
            "gen": {"status": "OK|SKIPPED|PENDING", "code": null, "step": null}}],   // train_doe만
 "warnings": [], "timing": {"total_s": 41.2}}
```
- 화면 폴링: `GET /doe-previews/{id}` 1 s(실행 중), 종료 시 멈춤.
- `train_doe`의 `gen`은 run 폴더 `SKIPPED.json`·starter 유무로 판정(DB 추가 없음, 응답 시 읽기 — `skipped_runs` 요약이 있으면 그것 우선).

### 6.7 DB — migration `0025_doe_preview`(down_revision `0024_contour3d_field`)

| 대상 | 변경 |
|---|---|
| `artifacts` | kind CHECK에 `GEOM_THUMB_PNG`(image/png) 추가. 셀 GLB·manifest는 기존 `GEOM_PREVIEW_GLB`·`GEOM_PREVIEW_MANIFEST` |
| `jobs` | `job_type` 허용 목록(CHECK가 있으면)에 `DOE_PREVIEW`, `ux_jobs_study_type_active` WHERE 제외 목록에 `DOE_PREVIEW` |
| `doe_previews`(신규) | `id UUID PK, study_id FK, created_by, job_id FK NULL, grid_key CHAR(64), source_kind VARCHAR(12), source_ref JSONB(param_set_id·doe_id·train_setup_id), matrix_key CHAR(64), select JSONB, status VARCHAR(12) CHECK(QUEUED,RUNNING,DONE,FAILED,CANCELED), cell_keys JSONB(페이지 셀 키 순서 + doe_no), n_total INT, n_ok INT, n_fail INT, n_error INT, timing JSONB, created_at, finished_at`. 인덱스 `(created_by, status)`, `(grid_key)` |
| `doe_preview_cells`(신규) | `cache_key CHAR(64) PK, study_id FK, status VARCHAR(12) CHECK(DONE,EXPIRED), result_status VARCHAR(8), code VARCHAR(64) NULL, category VARCHAR(16) NULL, max_disp_mm REAL, clipped BOOL, values JSONB, png_artifact_id, glb_artifact_id NULL, manifest_artifact_id, bytes BIGINT, engine_version VARCHAR(32), created_at, last_access_at`. 인덱스 `(last_access_at)`. ERROR 셀은 행을 만들지 않음 |

`values`는 이름→숫자 요약(파일 본문 아님). 번호는 구현 시점 HEAD 다음 번호가 우선(GV §6.7 원칙) — 바뀌면 변경 메모에 기록.

## 7. 표시 내용

| 요소 | 규칙 |
|---|---|
| 셀 그림 | 320×240 PNG(1:1 표시, 확대 축소 없음). 첫 셀 "공칭"(회색, 테두리 점선) |
| 셀 캡션 2줄 | 1줄: `run 17`(생성 전은 `#17` = doe_no) · 최대 변위 `0.42 mm`. 2줄: `top_changes` 3개 `THK_1 13.1(+5%) · HOLE_R 4.2(−8%) · 외 9`. 마우스 올림 = 전체 값 표(툴팁) |
| 변위 색 | 범례 1개(패널 상단): `turbo16` 0 ~ `disp_ref_mm` mm, 제목 "공칭 형상과의 거리(mm) — 모든 셀 같은 범위". 범위 밖 포화는 셀에 작은 "▲범위 초과" |
| 실패 | update FAIL: 빨간 2 px 테두리 + 배지(category, GV §7.3 문구 묶음) + `message_ko` 1줄(예 `GEOM_FEATURE_COLLISION` "피처 충돌 — THK_1·HOLE_R"), 그림은 공칭 + 원인 면 빨강. `ERROR`: 회색 점선 테두리 + "미리보기 오류 — 다시" |
| 잘림 | `clipped`면 셀 모서리 "잘림" 표시(축척 공통 유지가 우선) |
| 생성 후 겹침(`train_doe`) | 셀 우상단 작은 배지: 생성 OK(없음) / 스킵(빨강, `gen.code`·단계 — morph·check 실패 포함) / 대기. 미리보기 OK인데 스킵이면 배지만 빨강(DP-C9 차이 설명 툴팁) |
| 정렬·필터 | 툴바: 정렬 세그먼트 [변화 큰 순 \| DOE 순서 \| 변수 ▾ ↑↓], 체크 [실패만](렌더된 셀 중), 진행 "12/24 완료 · 실패 2 · 오류 0", [다음 24개], [취소] |
| 클릭 | 기존 3D 뷰어(GV §7.3 결과 표시 모드)를 대화상자로: 공칭 반투명 + 셀 GLB 변위 색(같은 범위) + 실패 빨강. 컨텍스트 1개, 닫으면 dispose. WebGL 불가면 같은 PNG를 2배 표시 + 값 표 |
| 낡음 | 요청 후 DOE 카드 입력(방식·run 수·seed·표)이 바뀌면 패널 상단 "설정이 바뀌었습니다 — [다시 미리보기]"(이전 격자는 흐리게 유지) |
| tag 없음(`train`) | 범례 아래 한 줄 "태그 전 미리보기 — 기준면은 추출 기본값이라 실제 생성 형상과 조금 다를 수 있습니다" |

## 8. 화면 위치

- **①-3 DOE 카드(Native, 단일 baseline)**: 실행 버튼 왼쪽에 [형상 미리보기](보조 버튼). 활성 조건 = 실행 버튼과 같은 표본 입력 검증 통과(run 수·seed·표 머리줄/범위) + `features.doe_preview`. Altair·다중 baseline이면 버튼 비활성 + 툴팁(문구 §5.1). 클릭 → 카드 바로 아래 전폭 카드 "형상 미리보기" 열림(격자 줄 전체 폭).
- **격자 배치**: 2560×1440 기준 셀 폭 360(그림 320 + 여백), 6열 × 4행 = 24. 1280~2399 폭은 4열, 그 미만 2열(같은 page_size, 행만 늘어남). 라이트 테마(흰 배경·회색 1 px 셀 경계).
- **생성 후 갤러리**: ①-3 DOE 선택 영역(Native DOE, 생성 단계 이후)에 [형상 갤러리] 버튼 → 같은 카드(`source.kind:"train_doe"`).
- **④·⑥**: 1차 미적용. ④ 일괄 Native 단일 baseline은 후속 1순위(같은 API에 `source.kind:"batch"`·`SITE_KINDS[batch]` 추가, 같은 카드 재사용). ⑥ 탐색은 대리모델 내부 표본이라 제외 권고.

## 9. 시험(V-DP-*)

| # | 항목 | 판정 |
|---|---|---|
| V-DP-1 | paicad 동결: 기존 `view export/preview`·`extract` PNG·`shell *` 출력·인자·시험 무수정 통과(`render.py` 일반화 후 피처 PNG 바이트 동일) | 통과 |
| V-DP-2 | 셀 = 단건: 가상 쿠션·SM1에서 `view grid` 셀의 `preview.glb`·`preview_manifest.json`(`thumb`·`timing` 제외) = 같은 값 `view preview --fe off` 출력 바이트 동일 | 바이트 동일 |
| V-DP-3 | 표본 일치: `train`·`param_set` 출처, `SITE_KINDS[train_native]` 각 kind(`lhs` 3모양 포함)의 미리보기 행렬 = 같은 본문의 `TD_DOE_GEN` DG_PREP `doe_matrix.csv` | 바이트 동일 |
| V-DP-4 | 공통 카메라: 서로 다른 표본 셀 2개의 `grid_manifest.camera.digest` 동일, 공칭 셀 PNG의 형상 외곽 픽셀 bbox = 계산 투영 bbox(±1 px), `disp_range_mm` 계산식·길이 단위만 | 통과 |
| V-DP-5 | 실패 셀: 충돌 값 → 셀 `FAIL`·`GEOM_FEATURE_COLLISION`·GLB 없음·PNG 있음(원인 면 빨강 픽셀 존재), 다음 셀 계속 처리, 셀 하나 `VIEW_TOO_LARGE` → 그 셀만 `ERROR` | 통과 |
| V-DP-6 | 결정성: `view grid` 2회 셀 산출물·`thumb.png` 바이트 동일 | 통과 |
| V-DP-7 | 작업·레인: `DOE_PREVIEW`가 CPU 대기열에서 `cpu.max_concurrent`에 세어짐, DP_RENDER `res=cpu`(정적 시험), PREVIEW 레인 단건 미리보기와 동시 실행, 청크 완료마다 셀 등록(폴링 중 증가), 취소 시 완료 셀 캐시 유지 | 통과 |
| V-DP-8 | 캐시: 셀 키 구성(값·tag·options·썸네일 옵션·버전 변경 시 다른 키, 출처·정렬·페이지는 같은 키), 전부 적중 → 200·작업 없음, 같은 grid_key 중복 반환, 이전 QUEUED 취소, 429, housekeeping이 `_cache/doe_preview/` 기간·합산 총량 삭제·링크 거부·410 | 통과 |
| V-DP-9 | 범위: Altair·다중 baseline → 409 `DOE_PREVIEW_UNSUPPORTED`, `features.doe_preview=false` → 409, `train` 출처 `tag_state:none` | 통과 |
| V-DP-10 | 화면(jsdom): 버튼 활성 조건 = 실행 검증, 정렬 3종·실패만(렌더된 셀만)·다음 페이지 offset, 셀 캡션 `top_changes`·실패 테두리·잘림·범례 범위, 낡음 표시, 클릭 → 뷰어 1개(동시 WebGL 컨텍스트 ≤ 1 계측), WebGL 불가 → 확대 PNG, 외부 URL 0건 | 통과 |
| V-DP-11 | 성능 기록: 가상 쿠션 24셀 `parallel` 2 전체 시간(목표 ≤ 90 s), 셀당 래스터 시간, 셀 PNG·GLB 크기. 현장: 실물 쿠션·chassis_rear 동일 수치 회신 | 측정·보고 |
| V-DP-12 | 생성 후 갤러리: fake DOE run 폴더(`SKIPPED.json` 1개 포함) → `gen.status`·code·step 표시, 행렬 = `D/doe_matrix.csv` | 통과 |
| V-DP-13 | MCP·정적: 새 API `x-mcp.exclude`, `DOE_PREVIEW` JOB_KINDS 제외 사유, migration 1개(0025)·down 관례, 새 런타임 의존 0(paicad·백엔드 pyproject 무변경) | 검사 |

`scripts/test-all` 통과가 완료 조건. fake_paicad에 `view grid`·`shell view grid`(합성 PNG 1개·GLB·manifest, `FAKE_PAICAD_FAIL=view_grid_cell:<idx>:GEOM_FEATURE_COLLISION`, `FAKE_PAICAD_SLEEP_S`) 추가.

## 10. 리스크

| # | 리스크 | 대응 |
|---|---|---|
| R1 | 실물 형상(삼각형 수십만)에서 셀당 시간·GLB 크기 과대 → 24셀 수 분 | 청크·병렬, GV LOD(`max_triangles`) 그대로, V-DP-11 현장 수치로 `page_size`·`parallel` 기본값 조정. 썸네일만 필요할 때 GLB 생략 옵션은 후속 |
| R2 | 미리보기가 CPU 슬롯을 써서 실행 중 DOE 생성과 경쟁(또는 CPU 4개가 차 있으면 대기) | `parallel` 2·`--threads 1`, 화면에 대기 순번 표시. 대기가 실사용 문제면 현장 회신 후 PREVIEW 레인 동시 수 확대를 후속 검토(Q3 확정은 CPU 대기열) |
| R3 | `train` 출처는 tag 전이라 기준면이 실제 생성과 다를 수 있음 | `tag_state:none` 안내, 생성 후 갤러리는 tag 사용(정답). 세트 기준 DOE는 차이 없음 |
| R4 | update만 보므로 morph·check 실패(`GEOM_QUALITY` 등)는 생성 전에 안 보임 | DP-C9를 범례·툴팁에 명시, 생성 후 갤러리 `gen` 배지로 보완. 격자 FE 검사는 비범위 |
| R5 | 공통 축척 때문에 변화가 작은 표본은 차이가 안 보이고, 큰 표본은 잘림 | 색(변위)이 주 신호, `clipped` 표시, 클릭 3D로 확대 |
| R6 | `disp_ref_mm`가 실제 최대 변위보다 크거나 작아 색이 단조로움/포화 | 범위 초과 표시, 현장 피드백 후 "보이는 셀 최대값" 모드는 후속(셀 캐시 키가 바뀌므로 1차 고정) |
| R7 | 캐시 총량(2 GiB 합산)이 GLB로 빨리 참 | 셀 GLB 크기 기록(V-DP-11), 필요 시 `geometry.view.cache.max_total_bytes` 상향 안내 |

## 11. 변경 범위·파일 소유

| 역할 | 범위 |
|---|---|
| Impl-Geom | `packages/paicad/src/paicad/view/grid.py`(신규), `shell/` grid 진입점, `cli.py`·`shell/cli.py` 하위 명령, `render.py` 일반화(크기·카메라·정점 색·공칭 외곽), 시험, `__version__` 0.14.0·CHANGELOG |
| Impl-Backend | `job_types.py`(`DOE_PREVIEW`), 워커 `steps/doe_preview.py`(DP_*), 행렬 계산 공용화(DG_PREP와 같은 함수 호출 — 함수 이동 없이 import), `commands.py` spec 2개·placeholder, config 스키마 `doe_preview`, API 라우터·서비스·스키마·`openapi.json`, housekeeping 대상 추가, `/status.features.doe_preview`, migration `0025_doe_preview`, fake_paicad, MCP 제외 표기, 시험 |
| Impl-Frontend | `stages/stage1/DoeGenCard.tsx`(버튼), 신규 `stages/stage1/doepreview/{DoePreviewCard,GridCell,gridModel}.tsx/ts`, 3D 뷰어 대화상자(기존 geomview 컴포넌트 재사용), mock·jsdom 시험, `frontend-dist/` |
| 순서 | 계약 확정 → GEOM(paicad 0.14.0, fake 병행) → BE → FE → Verifier(V-DP-1~13) |

## 12. 미결 처리(확정 2026-10-26)

- Q1 확정(사용자): 1차 범위 = ①-3 Native 단일 baseline의 생성 전 미리보기 + 생성 후 갤러리. ④ 일괄은 후속(1순위), Altair·다중 baseline·⑥ 제외(DP-C10).
- Q2 확정(메인 기본, 권고안 채택): 기본 표본 = 공칭 + 변화 큰 순 23개, 정렬은 [DOE 순서]·[변수 값↑↓]로 바꿀 수 있음(DP-C3·§5.2).
- Q3 확정(메인 기본, 권고안 채택): `DOE_PREVIEW`는 CPU 대기열(`cpu.max_concurrent`에 셈, DP_RENDER `res=cpu`)(DP-C6).
- 버전: v0.2.11, migration `0025_doe_preview`, paicad 0.14.0(`view grid` + rib-gap `RIB_GAP` 동시 포함).

## 변경 메모
- 2026-10-26 작성(Plan, 초안). GV §1.3 비범위 "DOE run별 형상 3D 보기"를 이 문서가 ①-3 Native 범위에서 대체(GV 변경 메모에 기록).
- 2026-10-26 확정 반영: Q1(사용자)·Q2·Q3(메인 기본 = 권고안), v0.2.11·`0025_doe_preview`·paicad 0.14.0(rib-gap `RIB_GAP`과 같은 버전) 배정.
- 2026-10-26 구현 통합 반영(DP-C 변경, 통합 담당 — 실제 paicad 0.14.0과 백엔드를 `worker/tests/stage4_predict/test_doe_preview_real.py`(실제 `view grid` 24셀·쉘 인자 배열)로 대조):
  - **DP-C12 ①-1 출처 쉘 판금**: `source.kind: "train"`의 features가 쉘(`shell_features.json`)이면 409 `DOE_PREVIEW_UNSUPPORTED`("쉘 판금 ①-1 기반 DOE는 고정 정보가 없어 형상 미리보기를 지원하지 않습니다 — 파라미터 세트 기준 DOE에서 쓰세요"). `paicad shell view grid`는 `--fixed-dir`이 필수인데 ①-1 기반 쉘은 DOE 실행 때 fixed-scan을 하므로 그 전에는 고정 정보가 없다. §5.1 표의 `train`은 솔리드만. 쉘은 `param_set`(`S/native/fixed`)·`train_doe`(`D/native/fixed`)에서만.
  - **DP-C13 `VIEW_*` ERROR 셀**: paicad는 `VIEW_*` 실패 셀을 manifest + 공칭 회색 썸네일이 든 셀 폴더로 남기고(`status:"ERROR"`), 내부 예외는 셀 폴더 없이 `GEOM_INTERNAL` ERROR 행만 낸다. 플랫폼은 둘 다 그 셀만 `ERROR`(캐시 안 함, 작업은 SUCCEEDED + 경고 `DOE_PREVIEW_PARTIAL`)로 처리한다(`judge_cell`: FAIL이어도 category가 VIEW·INPUT·INTERNAL이거나 code가 `VIEW_`로 시작하면 ERROR). §3.4 `ERROR` 정의를 이 규칙으로 읽는다.
  - **DP-C14 `nominal.view_sha256`**: `grid_manifest.nominal.view_sha256` = 공칭 테셀레이션 GLB(= `view export`/`shell view export --fixed-dir`와 같은 GLB)의 sha256. `--nominal-manifest` 인자는 없고 셀 manifest `nominal_ref.view_sha256`은 null이다(GV §4.3 셀 manifest의 이 키는 `view preview` 단건에서만 채워진다).
  - **DP-C15 빈 셀 목록**: `cells.json`의 `cells`가 빈 목록이면 입력 오류(종료 3, `GEOM_INPUT_INVALID`). 플랫폼은 렌더할 셀이 없으면(전부 캐시) 명령을 부르지 않고 DP_RENDER를 건너뛴다. §3.1 종료코드 3의 "입력 오류" 범위에 빈 목록·`thumb_options.json` 모르는 키·범위 밖 값이 들어간다.
  - **DP-C16 3D 대화상자 범례**: 격자 썸네일은 `turbo16` 16단계 이산 팔레트(§3.3, 격자 범례도 같은 표)이지만, 셀을 눌러 여는 3D 대화상자(기존 GV §7.3 결과 표시 모드 재사용)의 범례는 기존 **연속 컬러맵**이다(범위 `[0, disp_ref_mm]`은 같다). §7 "변위 색"·"클릭" 행의 "같은 범위"는 범위만 같다는 뜻이다.
  - 확인된 사실(변경 없음): 공칭 셀도 GLB·manifest를 낸다(`glb_artifact_id`·`manifest_artifact_id`, 3D 대화상자의 공칭 반투명 겹침에 쓴다). 페이지 `offset`은 첫 페이지(0) = 공칭 + `limit−1`개, 이후 = 정렬 순서의 `offset−1`부터 `limit`개(= 화면이 지금까지 받은 셀 수). `gen.step` 키 = 워커 `SKIPPED.json`의 실제 단계 이름 `update`·`morph`·`check`·`assemble`·`props`·`cushion`·`assign`(소문자). 실제 paicad 가상 쿠션 24셀(`parallel` 2, `chunk_cells` 4)은 렌더 약 12 s(OK 22 · FAIL 2 · ERROR 0)로 목표 ≤ 90 s를 만족한다(V-DP-11).
