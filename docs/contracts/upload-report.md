# 계약: 브라우저 입력 업로드(A) + HTML 결과 요약 보고서 받기(B)

> 상태: 확정(2026-10-21, 사용자 결정 반영 — 업로드 허용, U1~U3 확정 §12). **릴리스 v0.2.5**(v0.2.4 = native-vars + MCP 다음, 순차 — [roadmap.md](../roadmap.md)). migration `0021_uploads`(UR-C1).
> 상위 계약: [platform.md](platform.md)(§3.3·§17.5·V-SEC-1을 이 문서가 바꾼다 — 변경 메모 연결), [phase3.md](phase3.md) §12·D3-46(공유 inbox 흐름을 이 문서가 대체).
> 참고 구현(읽기 전용 이식 원본): `wgcha/esl-platform` 계약 `esl_p3_ux.md` §1.1·§2·§8·§9, `backend/esl_platform/core/uploads.py`·`api/services/uploads.py`·`api/routers/uploads.py`, `frontend/src/lib/uploader.ts`·`pages/newcase/UploadPanel.tsx`, `esl/report/html.py`·`api/html_report.py`, `backend/tests/test_p3_ux.py`·`test_p3_ux_hardening.py`. **동작·보호 규칙은 esl을 그대로 따르고, 다른 점만 이 문서에 적는다**(§2.3 차이표).

## 0. 한 줄 요약

입력(CAD·모델 폴더·학습 결과 폴더·Radioss 조립 폴더·템플릿 폴더 등)을 받는 모든 경로 칸에 **"내 PC에서 올리기 | 서버 경로" 두 탭**을 두고, PC 탭은 esl과 같은 **분할 업로드 세션**(청크 PUT·이어 올리기·청크 sha256·`.part`→최종 이름·덮어쓰기 금지·취소/낡음은 `_backup`)으로 `<ai_root>/uploads/<사용자>/<UTC>_<이름>/`에 저장한 뒤, **그 폴더 경로를 기존 경로 칸에 채워 기존 `paths/inspect`·작업 생성 흐름을 그대로 탄다**. 결과는 **⑤ 결과분석·⑥ 최적화부터**(U2) **서버가 만드는 단일 파일 HTML 보고서**(외부 자원 0, CSP 차단)를 받는다.

## 1. 배경·범위

### 1.1 사용자 결정(2026-10-21)

- 원문: "esl-platform 깃에서 참고해서 업로드 기능 가져오면 돼. 그거 잘되더라", "공유폴더 안돼".
- 대체되는 결정: decisions.md 2026-10-08 "업로드 기능 없음", 2026-10-16 D3-46(공유 `physicsai-inbox` 복사 후 찾아보기). platform.md §3.3 "`.psmdl` 업로드 비범위"·§17.5 "업로드 엔드포인트 없음".
- 유지되는 결정: pickle(`.pscfg`) 업로드·열기 금지(2026-10-07), SPDM master 쓰기 금지, 사용자 산출물 삭제 금지(`_backup` 이동), 경로 공백·cmd 메타문자 금지(2026-10-08), multipart 라우트 0개(V-SEC-1 — 청크 PUT `application/octet-stream`만).

### 1.2 범위

- (A) 업로드: 세션 API·DB(migration **0021**)·설정·파일 보호 규칙·프런트 업로더(esl 이식)·경로 칸 두 탭·`/fs/roots`에 업로드 루트 표시·환경 점검·감사 기록.
- (B) 보고서: 서버 생성 단일 HTML, 1차 대상 ⑤ 결과분석(결과 표 분석·등가성 판정 탭)·⑥ 최적화(내장·HyperStudy 레거시) — §9.1, 다운로드 API 1개, 파일명 규칙. ④ 예측·① DOE 보고서는 2차.

### 1.3 비범위

- esl §9 PC 도구(연결 코드·토큰·`*_extract.bat` 자동 올리기) — 이번 범위 제외(U3 확정). 후속 메모: physicsai는 학습에 **h3d 자체**가 필요하므로(esl처럼 추출 CSV로 대체 불가) 대안은 "PC에서 hvtrans로 h3d 축소(결과 종류·시점 선별) 후 자동 업로드". 실제 h3d 압축률(축소 전후 크기·학습 영향) 확인 후 별도 계약.
- ④ 예측(단건·일괄)·① DOE 요약 보고서 — 2차(U2).
- 업로드 폴더 자동 정리(COMPLETED 세션은 입력 원본이므로 보존) — 용량 표시만(§6.8), 정리 기능은 후속.
- SPDM 가져오기(`SPDM_IMPORT`) 칸 — 서버에서 SPDM을 읽는 기능이라 업로드 탭 없음.
- 보고서 PDF·PPTX, 3D 인터랙티브 뷰(GLB·three.js 내장) — 정적 이미지만.
- 브라우저 3D 화면 캡처를 보고서에 넣기 — 후속(§9.6).

## 2. 원칙

### 2.1 업로드는 "경로 만들기"일 뿐이다

업로드 세션이 끝나면(`complete`) 서버는 **폴더(또는 CAD 파일 1개)의 절대경로**를 돌려준다. 프런트는 그 값을 기존 `PathInput` 값에 넣고 기존 `POST /studies/{id}/paths/inspect` 결과 표시·작업 생성 요청을 **바꾸지 않고** 쓴다. 작업 params·워커·DB의 경로 열은 업로드 여부를 모른다(출처 표시는 `uploads` 행으로만).

### 2.2 업로드 루트 = AI 루트 아래 새 허용 루트

- `storage.upload_root`(기본 `"uploads"`)는 **AI 루트 기준 상대경로**(또는 AI 루트 하위 절대경로)다. 따라서 기존 `allowed_roots(imports=False|True)`·`check_user_path`가 **코드 변경 없이** 업로드 폴더를 받는다(AI 루트 전용 용도 `DATASET_INPUT`·`CURATION_INPUT`·`PARAM_SET`·④ 예측 경로 포함).
- 화면에는 별도 루트로 보인다: `GET /fs/roots`에 `{key:"upload", label:"내가 올린 파일", path}` 추가(inbox와 같은 바로가기 방식).
- AI 루트 밖 별도 드라이브는 U1(이번 범위 제안 = 허용 안 함 — AI 루트 전용 용도 검사 6곳을 고쳐야 하므로).

### 2.3 esl과 다른 점(이 표 외에는 esl 동작 그대로)

| 항목 | esl-platform | physicsai(이 계약) | 이유 |
|---|---|---|---|
| 세션 소속 | `project_id` | `study_id`(권한은 Study의 프로젝트 power) | physicsai 경로 확인이 Study 단위 |
| 세션 용도 | 첫 경로 성분 `rad/`·`results/`·`h3d/` | 세션당 `purpose` 1개, `rel`은 선택 폴더 기준 그대로 | 기존 `paths/inspect` purpose 재사용 |
| complete 검사 | rad 파싱·include | 해당 purpose의 **기존 `paths/inspect` 서비스 호출** | 검사 로직 단일 출처 |
| 저장 위치 | 절대 `storage.upload_root` | `<ai_root>/<upload_root>` | §2.2 |
| 파일 이름 규칙 | `< > : " | ? * & ^ % !`·예약어 | 위 + **공백·`; , = ( ) '`**(`name_unsafe_chars`) | physicsai 경로 규칙(D3-35)과 같아야 이후 작업 통과 |
| 허용 파일 | 확장자 목록 | **glob 패턴**(purpose별) + 항상 거부 목록 | T01은 확장자 없음(`*T01`) |
| 다른 사용자 폴더 | 읽기 격리(본인만) | 쓰기만 본인 세션, 읽기·찾아보기는 AI 루트와 같음(power) | AI 루트는 원래 팀 공용, Study 협업 |
| 디스크 검사 | 이 업로드 필요량 + 여유 | + **진행 중(OPEN) 세션 남은 양 합계** 예약 | 동시 대용량 업로드 경합 |
| 인증 | 쿠키 또는 PC 토큰 | 대시보드 쿠키만(PC 토큰은 U3 후속) | §1.3 |
| CSRF | esl 헤더 | `X-PhysicsAI-Request: 1`(platform §5.4) | 기존 규칙 |

## 3. 입력 대상과 화면 위치

### 3.1 purpose별 대상

| purpose(기존) | 화면(카드) | 형태 | 올릴 파일 패턴(기본, 설정 `upload.purposes.<P>.patterns`) | complete 결과 경로 |
|---|---|---|---|---|
| `CAD_FILE` | ①-1 `CadExtractCard` | 파일 1개 | native `geometry.step_extensions`(`*.stp`·`*.step`), altair `train_data.cad_extensions`(`*.prt`) — 요청 `engine`으로 고름(GE-C15) | 파일 경로 |
| `RADIOSS_ASSEM` | ①-3 `DoeGenCard` | 폴더 | `*.rad *.inc *.k *.key *.csv *.txt *.json *.dat` | 폴더 |
| `RESULT_FOLDER` | ①-5 `ResultCollectCard` | 폴더(대용량) | `train_data.collect_patterns`와 같은 값(기본 `*.h3d *T01 *_0000.out *_0001.out`) + `*.csv *.json *.txt` | 폴더 |
| `CURATION_INPUT` | ② `Sources` | 폴더(대용량) | `*.h3d *T01` + `*.csv *.json *.txt` | 폴더 |
| `DATASET_INPUT` | ③-1 `DatasetCards` | 폴더(대용량) | `*.h3d` + `*.csv *.json *.txt` | 폴더 |
| `MODEL_FOLDER` | ③-4 `ModelRegisterCard` | 폴더 | `*.psmdl` + `training_log.log_globs`(기본 `*.log *.txt`) + `*.json *.csv` — **`*.pscfg` 제외**(D3-43: pscfg 없이 등록 가능) | 폴더 |
| `PARAM_SET` | ④ `ParamSetCard`(템플릿 폴더) | 폴더 | `*.tpl *.prt *.stp *.step *.csv *.json *.txt *.rad *.inc *.k *.hm *.tcl` | 폴더 |
| `PREDICT_INPUT` | ④ `PreparedPredictCard` | 폴더 또는 파일 | `*.rad *.inc *.hm *.k *.csv *.json *.txt` | 폴더(파일 1개면 그 파일) |
| `DISCOVER`(업로드 전용 값) | ④ `ParamSetDiscoverForm`(프로젝트 폴더 자동 구성·native 세트 STEP+준비 폴더) | 폴더 | `PARAM_SET` ∪ `RADIOSS_ASSEM` 패턴 | 폴더 — complete는 형태 검사만(inspect 없음), 프런트가 기존 `param-sets/discover`를 부른다 |
| `FEM_ASSEMBLY` | ⑤ 등가성·FEM 검증 `SidePicker`(custom) | 폴더 | `RADIOSS_ASSEM` 패턴 | 폴더 — 2차 묶음(§10.3) |

- **항상 거부(설정으로 풀 수 없음)**: `*.pscfg`(pickle), `*.psdata`, 실행·스크립트 `*.exe *.dll *.pyd *.so *.bat *.cmd *.ps1 *.vbs *.js *.py *.lnk *.scr *.msi`, `*.part`(서버 임시 이름과 충돌). 오류 422 `UPLOAD_EXT_NOT_ALLOWED`(pscfg는 문구 "pscfg(pickle)는 올릴 수 없습니다 — 모델은 psmdl만으로 등록됩니다").
- 서버는 세션 생성 시 `rel`마다 **purpose 패턴 ∪ 전역 `upload.extra_patterns`** 와 대조한다(대소문자 무시, 파일 이름에만 적용). 프런트는 같은 패턴(`GET /uploads/config`)으로 폴더 선택 결과를 미리 거르고 "올릴 파일 N개 · 제외 M개(펼쳐 보기)"를 보여 준다(예: 결과 폴더의 `*.A001` 애니메이션은 자동 제외).

### 3.2 화면 — 두 탭

- `PathInput`(공통 컴포넌트)에 탭 `내 PC에서 올리기 | 서버 경로`를 붙인다. 서버 경로 탭 = 지금 화면(입력란 + 찾아보기 + 확인) 그대로. `BrowseButton`만 쓰는 화면(`PreparedPredictCard`·`ParamSetDiscoverForm`)은 같은 탭 래퍼 `PathSourceTabs`로 감싼다.
- 처음 탭: 사용자가 마지막에 고른 탭(localStorage `pai.pathSource`), 기록 없으면 "내 PC에서 올리기"(esl과 같음). `/status`의 `upload.enabled=false`(설정 없음·점검 실패)면 PC 탭을 숨기고 지금과 같다.
- PC 탭 구성(esl `UploadPanel` 이식, 화면당 주 버튼 1개 규칙 유지 — 카드의 주 버튼은 기존 실행 버튼, 업로드 버튼은 탭 안 보조 버튼):
  1. "파일 선택" / "폴더 선택"(`webkitdirectory`) / 끌어다 놓기. CAD는 파일만, 폴더 purpose는 폴더 우선.
  2. 미리 검사(네트워크 전): 패턴 제외 목록, 이름 규칙 위반(공백 등) 목록 — **위반이 1개라도 있으면 올리기 비활성 + "이름을 바꿔 다시 선택하세요"**(자동 이름 바꾸기 없음 — 파일 안 참조(include·tpl CAD 이름)가 깨지므로).
  3. 올리기: 진행률(전체·현재 파일), 속도·남은 시간, 멈춤/이어 올리기, 취소(받은 것은 `_backup`).
  4. 완료 → complete 결과 요약(기존 inspect 요약 컴포넌트 재사용) + 경로 칸에 값 채움 + "서버 경로" 탭으로 전환해 확인한 값을 보여 줌. 이후 흐름은 기존과 같다.
- 대용량 안내(결과·데이터셋 purpose): "h3d 30 GB ≈ 1 Gbps 약 5분, 100 Mbps 약 45분. 끊겨도 같은 폴더를 다시 고르면 받은 데부터 이어서 보냅니다. 탭을 닫지 마세요."
- 받은 파일 공유 폴더 안내 문구(`inbox_share_hint`)는 화면에서 내린다(키는 호환용 유지, §6.6).

## 4. API

모든 비GET 요청은 `X-PhysicsAI-Request: 1`(없으면 403 `CSRF_HEADER_REQUIRED`). 권한: 세션 생성·쓰기·완료·취소 = 해당 Study 프로젝트 power 이상(본인 세션만, 전역 관리자는 남의 세션 조회·취소 가능). 업로드 비활성 시 모든 쓰기 503 `UPLOAD_DISABLED`. 응답에 절대경로는 `path`·`display_path`만(platform B17 예외와 같은 표시용).

| 메서드·경로 | 요청 | 응답·오류 |
|---|---|---|
| `GET /uploads/config` | – | `{enabled, chunk_size, max_file_bytes, max_upload_bytes, max_files, max_concurrent_per_user, purposes:{<P>:{patterns, mode:"file"\|"dir"\|"dir_or_file"}}, always_denied:[...], free_bytes}` (로그인 사용자) |
| `POST /studies/{study_id}/uploads` | `{purpose, name, engine?:"native"\|"altair", files:[{rel, size, sha256?}]}` | 201 `Upload`. 422 `UPLOAD_NAME_INVALID`(+`rel`)·`UPLOAD_EXT_NOT_ALLOWED`·`UPLOAD_PURPOSE_INVALID`(`SPDM_IMPORT` 등)·`UPLOAD_SHAPE_INVALID`(CAD에 파일 2개 등), 409 `UPLOAD_FILE_DUPLICATE`(대소문자 무시), 413 `UPLOAD_TOO_LARGE`·`UPLOAD_TOO_MANY_FILES`, 429 `UPLOAD_LIMIT`, 507 `INSUFFICIENT_STORAGE` |
| `GET /studies/{study_id}/uploads?state=&mine=true` | – | 최근 50개 `Upload[]`(이어 올리기·출처 보기) |
| `GET /uploads/{id}` | – | `Upload`(파일별 `received`·`done`·`sha256`) |
| `POST /uploads/{id}/files` | `{files:[...]}` | OPEN 세션에 파일 추가(complete가 알려 준 누락분), 같은 검사 |
| `PUT /uploads/{id}/files/{index}?offset=` | body `application/octet-stream` ≤ `chunk_size`, 헤더 `X-Chunk-Sha256`(선택, 64 hex) | `{index, received, done, sha256}`. 409 `UPLOAD_OFFSET_MISMATCH`(+`received`)·`UPLOAD_FILE_DONE`·`UPLOAD_FILE_EXISTS`·`UPLOAD_CLOSED`, 413 `CHUNK_TOO_LARGE`, 415 `UNSUPPORTED_MEDIA_TYPE`, 422 `CHUNK_SHA256_MISMATCH`(쓰지 않음)·`CHUNK_OVERFLOW`·`SHA256_MISMATCH`(마지막 청크, `.part`는 `_backup`)·`PATH_UNSAFE`, 507 |
| `POST /uploads/{id}/complete` | – | `{upload_id, state, path, display_path, purpose, inspect: PathInspectResponse, problems:[...]}`. 모든 파일 `done` 아니면 409 `UPLOAD_INCOMPLETE`. inspect `ok=false`면 **OPEN 유지**(파일 추가 후 재시도), `ok=true`면 COMPLETED(이후 쓰기 409) |
| `DELETE /uploads/{id}` | – | OPEN만: 폴더를 `<upload_root>/_backup/<사용자>/<폴더명>`으로 이동, CANCELED. COMPLETED는 409 `UPLOAD_CLOSED`(입력 원본 보호) |
| `POST /admin/uploads/cleanup-stale` | – | 전역 관리자. 낡은 OPEN 세션 정리 즉시 실행 → `{moved:[id]}` |

- `Upload` = `{upload_id, study_id, purpose, engine, name, state:"OPEN"|"COMPLETED"|"CANCELED"|"STALE", path, display_path, chunk_size, total_bytes, received_bytes, files:[{index, rel, size, received, done, sha256, sha256_expected}], inspect, backup_display_path, created_by, created_at, updated_at, completed_at}`.
- `purpose`는 `PathInspectRequest.purpose` 값 중 `SPDM_IMPORT`를 뺀 것 + 업로드 전용 `DISCOVER`(inspect 없음, `inspect:null`). `paths/inspect`의 purpose 목록은 바꾸지 않는다.
- complete의 inspect는 `paths/inspect` 서비스 함수를 같은 인자(`purpose`, `path`, `engine`, `doe_id` 없음)로 직접 호출한다(HTTP 재호출 아님). `RESULT_FOLDER`처럼 `doe_id`가 필요한 확인은 complete에서 `doe_id` 없이 형식만 보고, 프런트가 기존대로 `doe_id`를 넣어 `paths/inspect`를 한 번 더 부른다.
- 낡음(STALE): `updated_at`이 `upload.stale_hours`(기본 72)보다 오래된 OPEN 세션 → `_backup` 이동. 세션 생성 때마다 + 관리자 API + 워커 하우스키핑(있으면)에서 실행. 파일 삭제 0.
- 감사(platform §17.6 `audit_events`): `UPLOAD_CREATE`·`UPLOAD_COMPLETE`·`UPLOAD_CANCEL`·`UPLOAD_STALE`(detail = purpose·파일 수·바이트·폴더 상대경로. 파일 이름 목록·내용·토큰 없음).
- `backend/openapi.json`에 청크 body를 `application/octet-stream` binary로 명시(esl `CHUNK_BODY`와 같음). multipart·`UploadFile`·`Form` 사용 금지(V-SEC-1 유지). python-multipart는 플랫폼 코드에서 import 금지 — MCP SDK(`mcp`)의 전이 의존으로 설치되는 것만 허용(UR-C1, mcp.md MR-18).

### 4.1 MCP 표기(mcp.md §15)

- §4 업로드 API 전부(`/uploads/config`·`/studies/{id}/uploads`(GET·POST)·`/uploads/{id}`·`/uploads/{id}/files`(POST·PUT)·`/uploads/{id}/complete`·`DELETE /uploads/{id}`·`/admin/uploads/cleanup-stale`)는 `x-mcp: {"exclude":"웹 파일 업로드"}` — LLM 클라이언트는 파일을 올리지 않는다. 따라서 API 토큰 요청은 403 `API_TOKEN_OPERATION_NOT_ALLOWED`(mcp MR-3), 업로드 인증은 대시보드 쿠키만(§2.3) 그대로.
- 동결 목록 `LEGACY_UNMARKED`에 넣지 않는다(새 operation 규칙).

## 5. 파일·폴더 보호 규칙(esl `core/uploads.py` 이식)

- 폴더: `<ai_root>/<upload_root>/<사용자 성분>/<UTC yyyymmdd-HHMMSS>_<이름>/<rel…>` — 이미 있으면 `_2`, `_3`…(`os.mkdir` 원자 생성, 덮어쓰기 없음). 사용자 성분 = 대시보드 username 정규화(실패 시 user_id).
- `rel`: `/` 구분, 절대경로·드라이브·`\`·`..`·`.`·빈 성분 거부, 성분마다 physicsai `name_unsafe_chars`(공백·`& | < > ^ % ! "`·`; , = ( ) '`·제어문자) + `path_component_problem`(끝 점·공백·`:`) + Windows 예약 장치명, 성분 ≤255자, rel ≤400자, **최종 절대경로가 `MAX_PATH_LEN`(400) 이하**(이후 `check_user_path` 통과 보장). 첫 성분 `_backup`·`_platform`·`.`으로 시작 거부(대소문자 무시).
- 쓰기: 상위 성분 링크·reparse point 거부(`is_link_or_reparse`), realpath가 세션 폴더 밖이면 `PATH_UNSAFE`. 새 `.part`는 `O_CREAT|O_EXCL|O_NOFOLLOW`, 이어 쓰기는 열린 fd로 일반 파일·링크 수 1 확인. 최종 이름이 이미 있으면 409(덮어쓰기 금지). 마지막 청크에서 전체 sha256(받으며 누적 계산) 확인 후 `os.rename(.part → 최종)`.
- `paths.assert_writable` 통과(SPDM 보호 루트 하위면 거부 — 설정 검사로도 막지만 이중 방어).
- 삭제 함수 호출 0: 취소·낡음·sha256 불일치 `.part`는 `<upload_root>/_backup/<사용자>/…`로 이동.
- 업로드 폴더 안에서 파일 내용을 열지 않는다(complete의 inspect가 기존 규칙대로 읽는 것 외). pickle·실행 파일은 패턴 단계에서 이미 거부.
- 동시성: 세션 행 `SELECT … FOR UPDATE` 아래에서만 청크를 쓴다(같은 파일 동시 쓰기 없음, PUT 순서는 offset으로 검증). 사용자당 OPEN 세션 수는 `pg_advisory_xact_lock(hashtext('pai-upload:'||user_id))` 아래에서 세고 넣는다. 누적 sha256 상태는 프로세스 메모리(재시작 시 받은 부분을 한 번 다시 읽어 복원 — esl과 같음). API 워커 프로세스가 여러 개여도 행 잠금으로 직렬화된다.
- 디스크 여유: 세션 생성·파일 추가 시 `free ≥ 이번 필요량 + Σ(다른 OPEN 세션의 남은 바이트) + upload.min_free_gb` 아니면 507. 청크 쓰기 중 `OSError(ENOSPC)`는 507 `INSUFFICIENT_STORAGE`(받은 데까지 유지 — 공간 확보 후 이어 올리기).

## 6. 설정·DB·배포

### 6.1 설정 키(`config/platform.example.yaml`, 하드코딩 금지)

```yaml
storage:
  upload_root: "uploads"        # AI 루트 기준 상대(또는 AI 루트 하위 절대). null = 업로드 끔(PC 탭 숨김)
upload:
  chunk_mb: 16                  # 1~64. 리버스 프록시 요청 크기 제한보다 작게(§6.5)
  max_file_bytes: 68719476736   # 64 GiB(h3d 30 GB급 수용)
  max_upload_bytes: 214748364800  # 200 GiB(학습 결과 폴더)
  max_files: 20000
  max_concurrent_per_user: 2
  min_free_gb: 50               # 업로드 뒤에도 AI 루트 드라이브에 남길 여유
  stale_hours: 72
  extra_patterns: []            # 모든 purpose에 더할 glob(항상 거부 목록은 못 풂)
  purposes: {}                  # purpose별 patterns 덮어쓰기(생략 = §3.1 기본)
```

- 설정 검사(`CONFIG_INVALID`): upload_root가 AI 루트 밖·`..`·공백·메타문자·`_backup`/`_platform`으로 시작·SPDM 루트와 겹침이면 오류. `extra_patterns`·`purposes`에 항상 거부 패턴이 들어오면 경고 후 무시.
- 기본값이 켜짐(`"uploads"`)인 이유: 사용자 요청 기능. 서버 경로 흐름은 그대로라 기존 동작은 바뀌지 않는다(2026-10-20 "새 키 기본값은 기존 배포 동작 불변"에 어긋나지 않음 — 화면에 탭이 추가될 뿐).

### 6.2 DB — migration `0021_uploads`

- down_revision = `0020_mcp`(v0.2.4 MCP, [mcp.md](mcp.md) §14). `MIGRATION_HEAD` = `0021_uploads`. 체인 `0019_extract_filter`(v0.2.3) → `0020_mcp`(v0.2.4) → `0021_uploads`(v0.2.5) 확정(UR-C1) — v0.2.4 배포 후 착수·병합하므로 번호 경쟁 없음.
- 테이블 `uploads`: `id UUID PK, study_id FK, project_id, user_id, username, purpose, engine NULL, name(≤200), dir_rel(AI 루트 기준), state CHECK(OPEN|COMPLETED|CANCELED|STALE), files JSONB array([{rel,size,sha256_expected,sha256,done}]), total_bytes BIGINT ≥0, inspect JSONB NULL(마지막 complete 요약 — 수치·이름 요약만), backup_rel NULL, created_at, updated_at, completed_at`. 인덱스 `(user_id, state)`, `(state, updated_at)`, `(study_id, created_at DESC)`.
- 경로는 AI 루트 기준 상대로 저장(platform §6.1 "경로·상태·수치 요약만"). 파일 본문 저장 금지. downgrade: 행이 있으면 거부(0017과 같은 정책).

### 6.3 환경 점검(env_check)

- `upload.root`: 폴더 존재(없으면 만들기 시도)·쓰기 시험(`_platform/env_check_tmp` 규칙과 같이 tempfile만)·여유 공간 표시(`min_free_gb` 미만 WARN). 설정 null이면 SKIP "업로드 꺼짐".

### 6.4 `/status`·`/fs/roots`

- `/status`에 `upload:{enabled, free_bytes}`. `/fs/roots`에 `upload` 루트(폴더가 있고 규칙 통과 시). `/fs/list`는 기존 규칙(`_backup` 숨김) 그대로 — 업로드 폴더의 `.part`는 목록에서 제외(진행 중 파일).

### 6.5 리버스 프록시(Caddy) 주의

- `deploy/caddy/physicsai.caddy`의 `handle /physicsai/api/*`는 요청 본문 상한을 두지 않는다(Caddy 기본 무제한, 요청 본문은 버퍼링 없이 스트리밍). **대시보드 Caddyfile 사이트 블록에 `request_body { max_size … }`가 있으면 `chunk_mb + 1 MB` 이상이어야 한다** — 배포 문서(admin.md)에 확인 항목 추가, 필요 시 스니펫 안 `handle /physicsai/api/uploads/*`에 `request_body { max_size 80MB }`를 명시(값은 설정 문서와 함께 관리).
- 서버 전역 `timeouts { read_body }`가 짧으면 느린 망에서 청크가 끊긴다 — 청크 1개(16 MB)를 10 Mbps에서 약 13초. 끊기면 클라이언트가 같은 offset으로 재시도(서버 received 기준).
- uvicorn·FastAPI: 청크는 스트림으로 읽으며 `chunk_size` 초과 즉시 413(메모리 상한 = 청크 1개). 액세스 로그에 쿠키·헤더 본문 없음(경로·상태·크기만) — 세션 토큰 로그 금지(AGENTS.md).
- 망 앞단에 다른 프록시(사내 웹 프록시 등)가 있으면 그 요청 크기 상한도 확인(e2e-checklist 항목).

### 6.6 기존 inbox(D3-46)

- `storage.inbox_dir`·`/fs/roots`의 `inbox` 루트는 호환용으로 남긴다(이미 들어 있는 파일을 계속 고를 수 있게). `inbox_share_hint` 안내 문구는 화면에서 내리고, 배포 스크립트의 SMB 공유 조회는 그대로 둬도 무해(삭제는 별도 정리 작업).

### 6.7 대용량(30 GB급)

- 파일당 64 GiB·세션당 200 GiB 기본. 브라우저: `File.slice` 스트리밍, 보내는 청크 1 + 미리 읽어 해시하는 청크 1(esl `PARALLEL=2`), 청크 sha256은 Web Crypto(비보안 http 컨텍스트면 생략 — 서버는 크기·전체 sha256으로 검증). 파일 전체 해시를 브라우저에서 미리 계산하지 않는다(30 GB 읽기 2회 방지) — `sha256` 선언은 선택.
- 이어 올리기: localStorage `pai.upload.<study>.<purpose>` = `{upload_id, files:[rel,size,lastModified]}`. 같은 파일 묶음을 다시 고르면 `GET /uploads/{id}`의 `received`부터. 서버가 STALE·CANCELED면 새 세션.
- 재시도: 네트워크 오류·5xx는 지수 백오프(최대 5회), 409 `UPLOAD_OFFSET_MISMATCH`는 서버 `received`로 맞춰 계속.
- 많은 파일(결과 폴더 수천 개): 파일 단위 순차, 작은 파일은 청크 1개. 진행 표시는 전체 바이트 기준.

### 6.8 용량 보기

- `GET /studies/{id}/uploads` 목록에 세션별 `total_bytes`. 업로드 루트는 Study 폴더 밖이라 phase3 §5 Study 용량 스캔·정리 범주에 들어가지 않는다(정리 대상 아님). 업로드 루트 전체 용량 표시·정리 기능은 후속.

## 7. 업로드 후 흐름(경로 기반 흐름 연결)

1. complete → `path` 반환 → `PathInput.onChange(path)` + 기존 inspect 결과를 그대로 `onInspected`에 전달(같은 모양).
2. 사용자가 기존 실행 버튼(예: ③-4 "모델 등록", ①-1 "파라미터 추출")을 누른다 → 기존 작업 params 검증(`check_user_path(allowed_roots(...))`)이 업로드 폴더를 AI 루트 하위로 받아 통과.
3. 기존 작업이 입력을 복사하는 곳(모델 등록 → `03_model/models/`, ① CAD·조립 사본 등)은 그대로 복사한다. 원본을 참조로만 쓰는 곳(③-1 데이터셋 `split.json` 절대경로, ② 원천 경로)은 업로드 폴더를 계속 참조하므로 **COMPLETED 세션은 지우거나 옮기지 않는다**(DELETE 409).
4. 작업 화면의 입력 경로 표시는 기존 `*_display_path` 그대로. 출처가 업로드면 경로 옆에 작은 문구 "내 PC에서 올림 · 10-21 14:02 · 홍길동"(작업 params 경로가 `uploads` 행 `dir_rel` 아래인지로 판정, 표시만).

## 8. Native/Altair 적용

- 업로드는 엔진 중립: 같은 세션 API·같은 탭. 엔진별 차이는 `CAD_FILE` 허용 확장자(요청 `engine`, GE-C15와 같은 기준)와 purpose별 패턴뿐. altair 카드(SimLab·NX)는 공통 `PathInput`을 통해 탭이 붙을 뿐 altair 추출·세트 등록 로직·설정은 바꾸지 않는다(extract-filter U3 "simlab은 건들지마" 범위 존중).
- 보고서도 엔진 중립: 엔진 표시(native면 paicad 버전·세트 종류 solid/shell, altair면 SimLab 템플릿 이름)만 다르다.

## 9. (B) HTML 결과 요약 보고서

### 9.1 대상과 순서(U2 확정 — "결과분석 및 최적화 위주")

화면 이름은 플랫폼 표기 그대로: **⑤ 결과분석**(`/stage/analysis`, `stages/stageAnalysis/`, s14_analysis.md §19 — 탭 `변수–응답`·`설계공간 지도`·`영향도`·`커브` + equiv-check.md §7 `등가성 판정` 탭), **⑥ 최적화**(`/stage/5`, `stages/stage5/` — 내장 `SURROGATE_OPT` 결과 `SurrogateResult`, 레거시 HyperStudy 결과 `OptResult`).

| 차수 | 대상(target) | 화면 | 원천(기존 API·파일, 읽기만) |
|---|---|---|---|
| 1차 | `analysis` | ⑤ 결과분석 — 결과 표 탭들 | 출처 `?source=batch\|doe&id=`(+ 선택 비교 `compare_source`·`compare_id`, 변수 `vars`·응답 `resp` 선택): 배치 = `GET /predict-batches/{id}`·`design-map`·`curves` 서비스, DOE = `GET /train-does/{id}/result-table` 서비스 |
| 1차 | `equiv-check` | ⑤ 결과분석 — `등가성 판정` 탭 | `eq_checks` 행(레시피 스냅숏·대상·판정·집계) + `recipe.json`·`pairs.json`·`metrics.csv`·`curves/*` |
| 1차 | `surrogate-opt` | ⑥ 최적화 — 내장(ego·ga·nsga2) | `GET /surrogate-opts/{id}`·`runs.csv`·검증(`verify`) 결과 |
| 1차 | `optimization` | ⑥ 최적화 — HyperStudy 레거시 결과(설정 시에만 존재) | `GET /optimizations/{id}` 서비스(결과 표·최적점) |
| 2차 | `predict`·`predict-batch` | ④ 예측 단건·일괄 | job result·`responses_pred.csv`·`curve.json`·컨투어 PNG / `predict-batches` |
| 2차 | `train-doe` | ① DOE 요약 | `train-does/{id}`·run 상태 |

- 1차 순서: RP1 = `surrogate-opt`·`optimization`(⑥) → RP2 = `analysis` → RP3 = `equiv-check`. (⑥ 원천은 서버에 이미 결과 모양이 있고, ⑤ `analysis`는 영향도 계산을 서버로 옮겨야 함 — §9.3.1.)
- ⑤ `analysis` 영향도(PRCC·표준화 회귀계수)는 지금 **프런트 TS 순수 함수**(`analysis/influence.ts`, s14 A5)다. 보고서용으로 서버에 같은 계산을 numpy로 둔다(`report_html/influence.py`) — 기준은 프런트 골든 `frontend/src/__tests__/fixtures/influenceGolden.json`과 **같은 값**(V-RP-4). 화면 계산은 그대로 둔다.

### 9.2 생성 위치 — 서버 생성, 저장 없이 스트리밍

- API 프로세스가 요청 시 DB 값 + 기존 산출 파일만 읽어 HTML을 만든다(외부 프로그램 실행 없음 — V-SEC-3 유지, 워커 작업 아님). 같은 입력이면 같은 바이트(생성 시각 줄 제외 — 시험은 시각 고정).
- 기본은 **디스크에 저장하지 않고 바로 응답**(사용자 산출물 증가·정리 문제 없음). 저장 옵션은 후속.
- 브라우저 생성(React → Blob)은 채택하지 않음: 오프라인·결정성·시험(Linux)·후속 MCP 요약 도구 재사용에 서버 쪽이 유리.
- 렌더러: esl `esl/report/html.py` 방식 이식 — `string.Template` + 고정 레시피, 모든 텍스트 `esc`, CSS 변수 라이트/다크, 그림은 **inline SVG**(선 그래프·산점·막대), 데이터는 inline JSON(작게), JS는 테마 전환·표 접기 정도의 소량 inline. 새 의존 없음(numpy만).

### 9.3 내용

공통 틀: ① 머리(제목 "⑥ 최적화 결과 요약" 등, Study·프로젝트, 대상 id 짧게·생성 시각·생성자·플랫폼 버전(`/version`)·엔진(+paicad 버전)) ② 입력 요약(모델 이름·라벨·Final·평가 점수, 파라미터 세트 라벨·engine·kind, 입력 경로 표시값 — 출처 "내 PC에서 올림" 문구 포함) ③ 대상별 본문(아래) ④ 상태·경고(실패·경고 코드) ⑤ 꼬리("이 파일은 외부 연결 없이 열립니다", 원천 id 목록). 그림은 inline SVG, 기존 PNG(컨투어 캡처·형상 미리보기)는 `data:image/png;base64`(이미지당 ≤ `report.max_image_bytes` 2 MiB, 총 ≤ `report.max_images` 24장 — 넘으면 "생략(n장)"). **3D는 정적 이미지만**(GLB·three.js 미포함). 표는 `report.max_table_rows`(500행) 상한, 넘으면 "전체는 화면의 CSV 받기" 안내.

#### 9.3.1 ⑤ `analysis`(결과 표)

- 출처 요약: 종류(일괄 예측·해석 DOE)·라벨·표본 방식(LHS 여부)·run 수(전체·유효)·비교 출처(같은 파라미터 이름 집합일 때만, s14 A6).
- 결과 표(파라미터 + 응답, 상한 행) + 응답별 통계(min·max·평균·표준편차).
- 변수–응답: 선택 변수(최대 4)×선택 응답 2D 산점 SVG(비교 출처는 속 빈 원 — 화면 규칙과 같음).
- 설계공간 지도: 화면 기본 축 2개 산점(색 = 응답, 색 막대) SVG.
- 영향도: 응답별 PRCC·표준화 회귀계수 표 + 막대 SVG, `influence_ok=false`면 사유 문구만(LHS 아님은 "참고용" 안내 — 화면 문구 그대로).
- 커브(출처 batch만): 겹쳐 그림(≤20개, 선택 run 강조).
- 보고서 요청 쿼리 = 화면 상태(출처·비교·`vars`·`resp`) — 프런트가 현재 선택을 그대로 넘긴다. 서버는 화면과 같은 기본값 규칙으로 빈 값을 채운다.

#### 9.3.2 ⑤ `equiv-check`(등가성 판정)

- 레시피 스냅숏(이름·버전·지표·허용오차·필수/참고), 대상(A·B 출처·쌍 수·미매칭), 종합 판정 배지, 지표별 표(차이·상대 %·상관·판정), 불합격 쌍 상위 목록, 대표 곡선 겹침 SVG(지표당 ≤3쌍).

#### 9.3.3 ⑥ `surrogate-opt`·`optimization`

- 설정: 목적(방향)·제약(임계값)·다목적 가중치·알고리즘·하이퍼파라미터·변수 범위(native-vars 스냅숏이 있으면 그 값, 없으면 세트 parameters).
- 결과: 최적점(단일) 또는 파레토 표(nsga2) + 파레토 산점 SVG, 수렴 이력·HV(있으면) SVG, 변수 쌍 산점(화면 `PairPlots`와 같은 쌍, ≤6), 성능 표.
- 검증: `verify` 결과(예측 vs 해석, 차이), 검증 안 함이면 "검증 없음".
- 레거시 `optimization`: HyperStudy 결과 표·최적점·반복 이력(있는 것만), 머리에 "HyperStudy(레거시)" 표지.

### 9.4 API·파일명

- `GET /reports/{target}/{target_id}?download=1` — target ∈ §9.1(구현된 것만, 나머지 404 `REPORT_TARGET_UNKNOWN`), 로그인 사용자(해당 Study 조회 권한). 대상이 끝나지 않았으면 409 `REPORT_NOT_READY`(⑥ 진행 중 최적화·⑤ 진행 중 배치 출처도 409 — 끝난 뒤 받기). `analysis`는 `target_id` 대신 쿼리 `source`·`id`(+`compare_source`·`compare_id`·`vars`·`resp`)를 받는다: `GET /reports/analysis?source=batch&id=…`.
- 응답 헤더(esl `html_report`와 같음): `Content-Type: text/html; charset=utf-8`, `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `download=1`이면 `Content-Disposition: attachment; filename*=UTF-8''…`. 크기 상한 `report.max_bytes`(기본 30 MiB) 초과 시 그림부터 줄이고, 그래도 넘으면 413 `REPORT_TOO_LARGE`.
- 파일명: `PAI_<Study 이름>_<target>_<id 앞 8자>_<YYYYMMDD-HHMM>.html`(예 `PAI_cushion55_surrogate-opt_3f2a91c0_20261021-1530.html`, `analysis`는 `analysis-batch`·`analysis-doe`). Study 이름은 `name_unsafe_chars` 문자·경로 구분자를 `_`로, ≤40자. 시각 = 서버 표준 시간대.
- MCP 표기(mcp.md §15): `GET /reports/{target}/{target_id}`·`GET /reports/analysis`는 `x-mcp: {"exclude":"HTML 파일 응답"}` — 단일 HTML(최대 30 MiB)은 도구 결과 상한(64 KiB)·텍스트 모델에 맞지 않는다. LLM은 같은 대상의 `get_summary`(`surrogate_opt`·`equiv_check`)를 쓰고, 사람에게는 화면의 "보고서 받기"를 안내한다. 보고서 링크를 돌려주는 도구는 후속 후보(§9.6).
- 화면: ⑤ 결과분석 머리 카드(`결과분석`·`등가성 판정` 탭 각각)와 ⑥ 결과 카드(`SurrogateResult`·`OptResult`) 머리에 보조 버튼 "보고서 받기(HTML)"(주 버튼 아님), 옆 링크 "새 탭에서 보기"(`download` 없이).

### 9.5 설정

```yaml
report:
  max_bytes: 31457280      # 30 MiB
  max_images: 24
  max_image_bytes: 2097152
  max_table_rows: 500
```

### 9.6 후속(이번 비범위)

- 2차 대상(④ 예측·① DOE), 화면 3D 뷰어 캡처(PNG)를 요청 본문(JSON base64, ≤ 5 MiB)으로 넘겨 보고서에 넣기, 서버 저장 옵션(`<study>/06_report/`), 여러 대상 묶음 보고서.

## 10. 구현 분해(파일 소유 비중첩)

### 10.1 Impl-Backend

| 파일 | 내용 |
|---|---|
| 신규 `backend/physicsai_core/uploads.py` | esl `core/uploads.py` 이식: 이름 규칙(physicsai `path_names` 재사용)·패턴 대조·폴더 생성·`target_path`·`append_chunk`·`_backup` 이동. DB·HTTP 없음 |
| `backend/physicsai_core/config/schema.py`·`rules.py` | `StorageCfg.upload_root`, `UploadCfg`, `ReportCfg`, 설정 검사(§6.1) |
| `backend/physicsai_core/db/tables.py` + 신규 `migrations/versions/0021_uploads.py` | §6.2, `MIGRATION_HEAD` |
| 신규 `backend/physicsai_api/{routers,services,schemas}/uploads.py` | §4. complete는 `services/path_inspect.py`의 purpose별 함수 호출(그 파일은 함수 노출만, 로직 무변경) |
| `backend/physicsai_core/fs_browse.py`·`services/fs_browse.py` | `upload` 루트, `.part` 숨김 |
| `backend/physicsai_core/env_check.py`(해당 항목 파일) | `upload.root` 점검 |
| 신규 `backend/physicsai_core/report_html/`(`page.py` 공통 틀·SVG, `opt.py`(⑥ 내장·레거시), `analysis.py`, `influence.py`(numpy PRCC·SRC — 프런트 골든 공유), `equiv.py`, 2차 `predict*.py`) + 신규 `physicsai_api/{routers,services}/reports.py`(원천은 기존 서비스 함수 호출만) | §9 |
| `backend/physicsai_api/main.py`(라우터 등록), `backend/openapi.json` | API 모양 먼저 |
| `config/platform.example.yaml`·`platform.demo.yaml`, `deploy/setup_config.py`(upload 폴더 생성), `deploy/caddy/physicsai.caddy`(주석·선택 `request_body`) | 배포 파일은 추가만(phase3 기준 유지) |
| 시험 `backend/tests/test_uploads*.py`·`test_reports*.py` | esl `test_p3_ux.py`·`test_p3_ux_hardening.py` 항목 이식 + §13 |

### 10.2 Impl-Frontend

| 파일 | 내용 |
|---|---|
| 신규 `frontend/src/lib/uploader.ts` | esl 이식(세션·청크·이어 올리기·재시도·Web Crypto), 저장 키 `pai.upload.*`, CSRF 헤더 |
| 신규 `frontend/src/components/upload/UploadTab.tsx`·`PathSourceTabs.tsx`·`uploadRules.ts`(패턴·이름 미리 검사 = 서버 규칙과 같은 표) | esl `UploadPanel` 일반화 |
| `components/PathInput.tsx` | 탭 래퍼 적용(purpose별 mode는 `BROWSE_OF` 확장) |
| `stages/stage4/PreparedPredictCard.tsx`·`ParamSetDiscoverForm.tsx` | `PathSourceTabs`로 감쌈 |
| `api/*`·`schema.d.ts`·`mock/*` | 업로드·보고서 목 |
| `stages/stage5/surrogate/SurrogateResult.tsx`·`stages/stage5/OptResult.tsx` | "보고서 받기" 버튼(1차 RP1) |
| `stages/stageAnalysis/StageAnalysis.tsx`(현재 출처·비교·변수·응답을 쿼리로)·`analysis/equiv/*`(결과 카드) | 1차 RP2·RP3 |
| 2차 `stages/stage4/PredictResult.tsx`·`batch/*`·`stages/stage1/*` | ④·① |
| `frontend-dist/` | 같은 커밋에서 재생성 |

### 10.3 묶음 순서

1. BE-UP1: core 규칙·설정·migration 0021·세션 API·x-mcp exclude 표기·시험(Linux). 2. FE-UP1: uploader·탭(①-1 CAD·③-4 모델·③-1 데이터셋·①-5 결과 먼저). 3. FE-UP2: 나머지 purpose(①-3 조립·② 원천·④ 템플릿·준비 입력·native 세트). 4. RP1: 보고서 ⑥(`surrogate-opt`·`optimization`). 5. RP2: ⑤ `analysis`(서버 영향도 + 골든 일치). 6. RP3: ⑤ `equiv-check`. 7. 2차: ④ 예측·① DOE. 8. `FEM_ASSEMBLY`(⑤ SidePicker) 업로드 탭·MultiBaseline은 마지막(선택).

## 11. 진행 중 작업과 충돌 지점

| 작업 | 겹치는 파일 | 처리 |
|---|---|---|
| extract-filter 구현(`feat/r1-v023`, **v0.2.3 병합 완료**) | `migrations`(0019 — 이 계약 체인의 시작), `db/tables.py`, `config/schema.py`, `openapi.json`·`schema.d.ts`, `CadExtractCard.tsx`(EF 필터 UI vs 업로드 탭 — 탭은 `PathInput` 안이라 카드 수정 최소), `ParamSetDiscoverForm.tsx`(EF native 필터 vs `PathSourceTabs` 래핑 — 직접 충돌) | **extract-filter 먼저 병합**, 업로드는 그 위로 rebase. 두 폼 파일은 업로드 쪽이 래핑만(필터 블록 미접촉) |
| native-vars(`docs/native-vars`, 계약 단계) | `openapi.json`·`schema.d.ts` 재생성, ⑥ 보고서가 `settings.vars` 스냅숏을 읽음, `SurrogateSetup.tsx`·`ResultCards.tsx`(NV) vs `SurrogateResult.tsx`(보고서 버튼) 인접 | RP1은 스냅숏 있으면 우선·없으면 세트 parameters로 읽어 NV 병합 전후 모두 동작. NV가 먼저 병합되면 그 위로 rebase. migration 없음 |
| MCP(v0.2.4, [mcp.md](mcp.md)) | `migrations`(0020_mcp → 이 계약 0021 down_revision), `db/tables`, `config/schema.py`, `main.py`(라우터 등록·MCP 마운트), `openapi.json`·`operation_ids.txt`, `deploy/caddy/physicsai.caddy`(MCP `handle` vs 업로드 `request_body` 주석), `deploy/requirements.lock` | **v0.2.4 배포 후 착수**(순차). 새 operation은 x-mcp exclude(§4.1·§9.4) — V-MCP-6이 검사 |
| equiv-check(⑤ 등가성 판정 탭) | `eq_checks`·결과 파일 읽기만, `analysis/equiv/*` 결과 카드에 버튼 | RP3. equiv 구현 병합 후 착수 |
| S14 ⑤ 결과분석 | `analysis/influence.ts` 골든 공유 | 화면 계산 무변경, 서버는 골든으로 일치 검사 |

## 12. 사용자 결정(2026-10-21 확정)

| # | 질문 | 결정 |
|---|---|---|
| U1 | 업로드 저장 위치 | `<ai_root>/uploads`(AI 루트 하위 — 기존 경로 검사 그대로, 용량은 AI 루트 드라이브 공유) |
| U2 | 보고서 범위 | "결과분석 및 최적화 위주": 1차 = ⑤ 결과분석(결과 표 분석·등가성 판정 탭) + ⑥ 최적화(내장·HyperStudy 레거시), ④ 예측·① DOE는 2차 |
| U3 | esl §9 PC 도구 이식 | 이번 범위 제외. 후속: h3d가 학습에 필요하므로 "PC에서 hvtrans로 h3d 축소(결과·시점 선별) 후 자동 업로드" — 실제 압축률 확인 후 별도 계약 |

## 13. 검증 기준

### 13.1 업로드(V-UP)

| ID | 기준 | 방식 |
|---|---|---|
| V-UP-1 | 생성→청크→complete 정상 흐름, `path`가 기존 `paths/inspect`·작업 생성(③-4 모델 등록, ①-1 CAD)에서 그대로 통과 | API |
| V-UP-2 | offset 순서 위반 409(+received), 재시도·이어 올리기, 청크 sha256 불일치 422(쓰기 0), 파일 sha256 불일치 시 `.part`가 `_backup`으로 | API |
| V-UP-3 | 이름 공격(`..`·절대경로·`\`·드라이브·예약어·끝 점·공백·`& ( ) ; , = '`·제어문자·`_backup` 첫 성분) 422, 세션 폴더 밖 쓰기 0(심링크·하드링크·junction 대체) | API·파일시스템 |
| V-UP-4 | 패턴 밖·항상 거부(`*.pscfg`·`*.psdata`·실행 파일·`*.part`) 422, 설정으로 항상 거부를 풀 수 없음 | API·단위 |
| V-UP-5 | 크기 상한(파일·세션·파일 수) 413, 여유 공간 부족(다른 OPEN 세션 예약 포함) 507, 청크 중 ENOSPC 507 후 이어 올리기 | API(디스크 함수 대체) |
| V-UP-6 | 권한(viewer 403·남의 세션 404·관리자 조회/취소), CSRF 헤더 없으면 403, 사용자당 동시 2 초과 429 | API |
| V-UP-7 | 취소·낡음 → `_backup` 이동·삭제 호출 0(정적: 업로드 모듈에 `os.remove`·`unlink`·`rmtree` 없음), COMPLETED DELETE 409 | API·정적 |
| V-UP-8 | complete inspect 실패 시 OPEN 유지 → 파일 추가 → 재complete 성공(모델 폴더 psmdl 누락 예) | API |
| V-UP-9 | multipart 라우트 0개 유지(V-SEC-1), 플랫폼 코드 python-multipart import 0(MCP SDK 전이 의존 설치는 허용 — UR-C1), 업로드 API에 `pai_` 토큰 403, 업로드 로그에 쿠키·토큰 없음 | 정적·로그 |
| V-UP-10 | 설정 검사(upload_root가 AI 루트 밖·SPDM 겹침·`_platform` 오류), null이면 503·PC 탭 숨김, env_check 항목 | 단위·UI |
| V-UP-11 | `/fs/roots`의 upload 루트, `/fs/list`에서 `.part`·`_backup` 숨김 | API |
| V-UP-12 | UI: 두 탭·미리 검사(제외·이름 위반 시 올리기 비활성)·진행률·멈춤/이어 올리기(탭 재시작)·완료 후 경로 채움 — mock + 실서버 Playwright, 주 버튼 1개 규칙 | UI |
| V-UP-13 | 대용량: 1 GiB 이상 파일 스트리밍(메모리 = 청크 1개 수준), 64 GiB 상한 경계값 | API(희소 파일) |
| V-UP-14 | 현장(e2e-checklist): Caddy 경유 16 MB 청크 PUT 성공, 30 GB h3d 업로드·이어 올리기·③-1 데이터셋 생성까지 | 수동 |
| V-UP-15 | migration 0021 up/down(행 있으면 down 거부), down_revision `0020_mcp`, `MIGRATION_HEAD`=`0021_uploads`, 모든 업로드·보고서 operation에 x-mcp exclude(V-MCP-6), `scripts/test-all` 통과 | 시험 |

### 13.2 보고서(V-RP)

| ID | 기준 | 방식 |
|---|---|---|
| V-RP-1 | 응답 HTML에 외부 URL 0건(`http(s)://`·`//` 로딩 컨텍스트 — `<script src>`·`<link href>`·`url(`·`@import`·`<img src>`가 `data:` 아님), CSP·nosniff·no-store 헤더 | API·정적 |
| V-RP-2 | `download=1` 첨부·파일명 규칙(한글 Study 이름·금지 문자 치환·`filename*`) | API |
| V-RP-3 | ⑥ `surrogate-opt`: 설정(목적·제약·가중치·알고리즘)·최적점 또는 파레토 표·수렴/HV·쌍 산점 SVG·검증 결과가 들어감(ego·ga·nsga2 각 1건), `optimization`(레거시) 결과 표·표지, 레거시 미설정이면 404 | API(fake 결과) |
| V-RP-4 | ⑤ `analysis`: 출처 batch·doe 각각 결과 표(500행 상한)·통계·변수–응답·설계공간 지도·커브(batch만), 비교 출처(이름 집합 다르면 비교 생략 문구), **서버 영향도 값 = 프런트 골든 `influenceGolden.json`**(허용오차 1e-9), `influence_ok=false` 사유 문구 | API·단위 |
| V-RP-4b | ⑤ `equiv-check`: 레시피 스냅숏·판정 배지·지표 표·불합격 쌍·곡선 SVG, 삭제된 레시피 이력도 스냅숏으로 표시 | API |
| V-RP-5 | 모든 사용자 문자열 이스케이프(라벨에 `<script>` 넣어 그대로 표시), 결정성(시각 고정 시 바이트 동일) | 단위 |
| V-RP-6 | 크기 상한 초과 413, 없는 target 404, 끝나지 않은 대상 409, 권한 | API |
| V-RP-7 | API 프로세스 외부 프로그램 실행 없음(V-SEC-3 유지) | 정적 |
| V-RP-8 | UI: ⑤(두 탭)·⑥(내장·레거시) 보조 버튼·새 탭 보기(주 버튼 아님), ⑤는 현재 선택이 쿼리로 넘어감, 오프라인 브라우저에서 파일을 열어 그림·표 표시(수동) | UI·수동 |

## 14. 리스크

| # | 리스크 | 대응 |
|---|---|---|
| R1 | 업로드가 AI 루트 드라이브를 채움(COMPLETED는 보존) | 생성 시 여유 검사·예약, env_check WARN, 용량 표시, 정리 기능 후속 |
| R2 | 사용자 파일 이름에 공백·괄호가 흔함(예 `model (1).h3d`) → 올리기 거부 | 미리 검사로 즉시 목록 표시. 자동 이름 바꾸기는 참조 파손 때문에 하지 않음 |
| R3 | 대시보드 Caddy·사내 프록시의 본문·시간 제한 | §6.5 확인 항목, 청크 크기 설정으로 조정, 현장 V-UP-14 |
| R4 | API 프로세스가 대용량 쓰기로 응답성 저하 | 청크 쓰기는 threadpool, 사용자당 동시 2, 청크 16 MB |
| R5 | 다른 사용자가 남의 업로드 폴더를 입력으로 지정 | AI 루트와 같은 공용 정책(의도). 쓰기는 본인 세션만, 출처 문구로 누가 올렸는지 표시 |
| R6 | `.psmdl` 내부 형식 미상(pickle 계열 가능성) | 플랫폼은 열지 않음(기존과 같음 — edspy만 연다). 경로 지정 흐름과 위험 동일 |
| R7 | extract-filter·MCP와 migration·폼 파일 충돌 | §11 순서(EF v0.2.3 완료 → MCP v0.2.4 → 업로드 v0.2.5) |

## 변경 메모(UR-Cn)

- **UR-C1**(2026-10-21, Plan — 사용자 릴리스 배정): v0.2.5로 배정(v0.2.4 native-vars + MCP 다음, 순차). migration `0020_uploads` → **`0021_uploads`**(down_revision `0020_mcp`). 업로드·보고서 API x-mcp exclude(§4.1·§9.4). "python-multipart 의존 추가 금지" → 플랫폼 코드 import 금지 + MCP SDK 전이 의존만 허용(공식 SDK `mcp`가 python-multipart를 필수 의존으로 가짐 — 2.3.0 METADATA 확인). multipart 라우트 0개(V-SEC-1)는 그대로.
