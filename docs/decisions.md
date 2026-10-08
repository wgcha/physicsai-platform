# 결정 기록

형식: `날짜 · 결정 · 근거 · 참조`. 뒤 결정이 앞 결정을 대체하면 "대체"로 표시한다.

## 2026-10-07 (대시보드 통합 초안 시기 — 아래 항목은 유효한 것만 옮김)

- 2026-10-07 · 실행 위치는 대시보드와 같은 Windows PC, Altair 2026.1 실행 경로는 설정 키(`hyperstudy_path`·`simlab_path`·`edspy_path`·`hw_exe_path`·`hvtrans_exe_path`)로만 지정, 하드코딩 금지 · GPU·라이선스가 이 PC에 있고 원본 앱과 같은 키로 이식 · platform.md §9.1
- 2026-10-07 · 로컬 실행 슬롯은 전역 1개, 나머지는 FIFO 대기(대기 순번 표시) · 하드웨어 제약 · platform.md §7
- 2026-10-07 · 워커는 별도 프로세스·pull 방식, owner/token/generation CAS lease, Windows Job Object(CPU hard cap·BELOW_NORMAL·메모리 상한·하위 프로세스 포함·취소=TerminateJobObject), GPU 무제한, 기본 32코어/64GB · API 응답성 보호와 장애 격리 · platform.md §11
- 2026-10-07 · PBS는 `HpcJobGateway`(none|command|adapter) 뒤에 두고 command는 argv 템플릿·정규식·상태맵 설정값, adapter는 자리만 · 사내 어댑터 job API 미확인, 나중에 명령만 교체 · platform.md §12
- 2026-10-07 · PBS 해석 중에는 로컬 슬롯을 놓고 회수 후 다시 대기열 뒤에 선다 · 장시간 PBS 대기가 로컬 자원을 막지 않게 · platform.md §7.2 T5·T14
- 2026-10-07 · 산출물은 SPDM master 밖 AI 루트(임시 `E:\shared\AI_WORK`)에만, 기존 산출물은 삭제 대신 백업 폴더로 이동, 잠김 시 실패 · SPDM 보호·덮어쓰기 사고 방지 · platform.md §8.3, §15
- 2026-10-07 · pscfg(pickle)는 업로드 금지 · pickle 역직렬화 코드 실행 위험 · platform.md §17
- 2026-10-07 · UI는 경로바 + 5단계 스텝퍼 + 좌측 작업영역 + 우측 공통 패널, 단계별 실행 버튼 1개, 4K 32인치 고려 · 사용자 합의 · platform.md §16
- 2026-10-07 · (대체됨 → 2026-10-08) 대시보드 저장소 안에 기능 통합, DuckDB 개발 모드 병행, 5단계 전부 1차 범위, 플랫폼이 학습 실행·실시간 loss, ④ 기본 경로 RUN_NOMINAL

## 2026-10-08 (별도 플랫폼 확정)

- 2026-10-08 · 대시보드와 분리된 신규 플랫폼(저장소 `wgcha/physicsai-platform`): frontend React+Vite+TS / backend FastAPI / worker 별도 프로세스 / PostgreSQL 전용(같은 서버 별도 DB, Alembic), DuckDB 미사용 · 대시보드 변경 위험 차단, 워커 다중 프로세스 쓰기에 PG 필요 · platform.md §4
- 2026-10-08 · 배포는 Windows Server 폐쇄망·대시보드와 같은 PC, 같은 주소의 `/physicsai/` 하위 경로(Caddy), 오프라인 wheel·deploy.bat은 2차(1차는 개발 실행 스크립트) · 같은 origin으로 로그인 공유, 1차 범위 축소 · platform.md §4.2, §4.6
- 2026-10-08 · 대시보드 로그인 공유: 같은 origin 쿠키 `analysis_canvas_session`을 받아 대시보드 `GET /api/auth/me`로 매 요청 확인(30초 캐시), 대시보드 코드 변경 없음 · 관리형 로컬 실행과 같은 "신원은 대시보드가 확정" 원칙, 기존 API로 충분 · platform.md §5
- 2026-10-08 · Study는 대시보드 프로젝트에 소속. 조회는 로그인한 모든 사용자, 실행(대기열 등록)은 power·admin, 대기열 관리(순서 변경·취소)는 admin — admin은 전역 관리자로 해석(사용자 확인 대기, U10) · 대시보드 역할 체계 재사용, 대기열은 전역 자원 · platform.md §5.3
- 2026-10-08 · 실행 시간 한도 없음, 오래 걸리면 관리자가 수동 취소 · 해석·평가 시간 예측 불가 · platform.md §7.1
- 2026-10-08 · 1차 범위 = 대기열·워커 + ③ + ④ + 알림 + 공통 셸. ①②⑤·PBS 실제 연동·대시보드 Case 결과 가져오기는 2차(화면에는 단계 표시·비활성 안내) · 가장 가치 큰 예측 흐름부터 · platform.md §3
- 2026-10-08 · ③ 재정의: 데이터셋 생성(로컬 edspy, 입력 h3d 폴더는 AI 루트 하위 경로 지정, 10% 홀드아웃·고정 seed로 학습용/평가용 2개) → 학습 패키지 내보내기 → HPC 학습은 사용자가 직접 → 모델 폴더 등록 → 로컬 GPU 평가 → Study당 Final 1개 지정 · 학습은 HPC 자원이 필요하고 플랫폼 관여 불필요, 홀드아웃으로 공정 평가 · platform.md §8.4~§8.7
- 2026-10-08 · 학습 로그 파서는 플러그형 정규식(기본 원본 `epoch=… loss=…`), 파싱 실패해도 등록 성공·"로그 형식 미확인" 표시 · HPC 로그 형식 미정 · platform.md §8.6
- 2026-10-08 · pscfg 템플릿 생성 기능은 만들지 않는다. pscfg는 경로만 기록하고 edspy에만 전달 · pickle 위험, 사용자가 HPC에서 직접 준비 · platform.md §8.6, U7
- 2026-10-08 · ④ 파라미터 정의·학습 샘플은 Study에 CSV/JSON 폴더 경로로 등록(① 연동은 2차), 체인 = 형상(SimLab) → 메싱(학습과 같은 tpl) → .rad 조립 → edspy `--predict-write`(env `EDS_TNS_ACTVN_CHCKPT=1`, Final 기본) → 컨투어 · ① 이력이 1차에 없음 · platform.md §8.8~§8.9, §15.4
- 2026-10-08 · ④ 구현은 RUN_NOMINAL 재사용 대신 개별 명령 체인. 원본으로 확인 안 되는 단계(형상 갱신·메싱·.rad 조립·응답 추출)는 설정 명령 템플릿 + "사내 확인 후 교체" · 최적화 코어(pyd) 동작 미검증 · platform.md §9
- 2026-10-08 · 컨투어는 A안: 원본 `BATCHRUN_preview_pred_h3d.tcl` 출력을 가공 없이 표시 · 신규 TCL 작성 위험 회피 · platform.md §8.9, U4
- 2026-10-08 · 학습 범위 밖 입력은 경고 배지 없이 작은 참고 문구("학습 범위 밖 · 최근접 run_xxxx")만 · 사용자 판단 존중, 화면 단순화 · platform.md §8.8
- 2026-10-08 · DB에는 경로·상태·수치 요약(점수, loss 배열 등)만, 파일 본문 금지. 산출물은 AI 루트에만, SPDM master 쓰기 금지, AI 루트에 공백·cmd 메타문자 금지 · 데이터 위치 단일화, `.bat` 인자 안전 · platform.md §6.1, §17
- 2026-10-08 · 알림: 작업 시작/완료/실패/내 차례 도래/PBS 회수 완료 시 우하단 토스트, 벨 아이콘 미읽음 수, 30일 이력·읽음 처리, 폴링 기반 · 장시간 작업 인지 · platform.md §13
- 2026-10-08 · 단위계 mm-ton-s 고정, 변환 없음 · 해석 모델 단위계와 일치 · platform.md §2
- 2026-10-08 · 업로드 기능 없음, 모든 입력은 AI 루트(또는 허용 루트) 폴더 경로 지정 · 대용량 파일·pickle 위험 · platform.md §3.3, §17.3
- 2026-10-08 · 자동 시험은 Altair 없는 Linux에서: fake tools(edspy/SimLab/hw/qsub) + Job Object 비Windows 대체(PosixLimiter). 실제 E2E는 사용자가 Altair PC에서 체크리스트로 수행 · 개발 환경에 Altair 없음 · platform.md §18, e2e-checklist.md
- 2026-10-08 · 대기열 취소·순서 변경은 전역 관리자만, 본인 작업 취소도 불가(재시도만 본인 power 허용) · 대기열은 프로젝트를 가로지르는 전역 자원, U10 · platform.md §5.3, §19 U10
- 2026-10-08 · ④ "입력파일 받기" `GET /jobs/{id}/artifacts/input.zip`(INPUT 폴더 zip 스트리밍, 로그인 사용자 전원, .rad 조립 완료 전 409) · 사용자가 HPC·로컬에서 Radioss 입력을 직접 확인·실행 · 변경 메모 B16
- 2026-10-08 · 응답 "절대경로 금지"의 예외로 표시 전용 `*_display_path`(ai_root 결합, 탐색기 붙여넣기용) 허용, 요청 입력으로는 받지 않음 · 사용자가 산출 폴더를 바로 열 수 있게 · 변경 메모 B17
- 2026-10-08 · 워커 자식 프로세스 환경변수는 허용목록(SystemRoot·PATH·TEMP/TMP·USERPROFILE·ALTAIR_*·*_LICENSE_*·EDS_* + 설정 `worker.env_passthrough`)만 전달, DB URL·비밀은 항상 제외 · 비밀 유출 차단 · 변경 메모 B19

## 2026-10-08 (2차 계약 — 사용자 부재 중 Plan 결정, "가정"은 사용자 확인 대기)

- 2026-10-08 · (가정) 2차는 Altair 실제 실행 확인 없이 독립 구현·자동 시험 가능한 범위만 진행: 환경 점검, 오류 묶음, ①②⑤, ①→④ 파라미터 세트, SPDM 읽기 전용 가져오기, 배포 스크립트, 알림·대기열 확장. 원본으로 확인 안 되는 인자·파일 위치·출력 형식은 설정 템플릿·플러그형 파서 · 사용자 부재, 1차와 같은 원칙 · phase2.md §2, §17
- 2026-10-08 · 1차 변경 메모 B1~B26 전부 수용(1차 기준선) · 1차 구현·검수 결과와 일치 · phase2.md §0
- 2026-10-08 · (가정) 환경 점검은 작업 대기열이 아닌 전용 테이블: API가 DB·대시보드·설정·PBS 모드를 즉시 점검, 실행 파일·AI 루트 쓰기·Job Object·GPU는 워커가 비동기 점검. 실행 파일 짧은 실행은 기본 "존재 확인만", 인자는 설정 템플릿 · API 외부 실행 금지(AGENTS.md), Study 비소속 · phase2.md §9, A-12, U32
- 2026-10-08 · (가정) 오류 묶음 zip은 작업 등록자 본인과 전역 관리자만 받는다(명령 스냅샷·설정 요약 포함), 비밀·토큰·DB URL 마스킹, 로그는 꼬리만 · 1차에서 명령은 관리자 전용 · phase2.md §10, A-13, U33
- 2026-10-08 · pyd 코어는 원본처럼 작업 폴더로 런처와 함께 복사 후 SimLab·hstbatch·hstpy가 실행, 플랫폼 프로세스는 pyd를 import하지 않음 · 보안·원본 동작 보존 · phase2.md §4.2
- 2026-10-08 · ①-2 tpl 생성은 원본 `update_parameter_file` 정규식 치환을 우리 코드로 재구현(동기 API), 기본 범위 ±5%·형식 `%3i`는 원본값을 설정 기본으로, 정수 형식+비정수 범위는 경고 · 원본 로직이 순수 텍스트 변환 · phase2.md §6.3, U23
- 2026-10-08 · (가정) ①-2 "사용 여부" 열 추가, 사용 안 함 파라미터는 tpl 두 블록에서 제외(CAD 공칭 유지 가정) · 원본에 없는 사용자 요구 · phase2.md §6.3, A-5, U37
- 2026-10-08 · (가정) DOE 샘플 값은 run 폴더의 렌더링된 tpl `paramitem NewValue`에서 읽는 추출기를 기본으로(csv·none 선택), 없으면 ①→④ 자동 생성만 막음 · pyd 출력 형식 미확인 · phase2.md §6.4.1, U18
- 2026-10-08 · ①-4 PBS는 run마다 제출, 일부 실패면 성공 run을 회수(T10b, 설정으로 전체 실패 선택 가능), gateway none이면 "PBS 연결 안 됨" + 사용자가 수동 해석 후 결과 폴더를 지정하는 `TD_RESULT_IMPORT` · PBS 미확인·장시간 해석 일부 실패 대비 · phase2.md §6.5~§6.6, §7.1
- 2026-10-08 · (가정) 회수 모드 `drive`는 `shared_folder`의 별칭(설정 루트에서 Study로 복사), 수동 지정 폴더 회수는 별도 작업 · 작업 지시 해석 · phase2.md §6.5, A-7, U36
- 2026-10-08 · ② 큐레이션 hvtrans cfg·곡선 입력 JSON·run 폴더 이름 규칙은 원본 GUI 로직을 그대로 재구현, hvtrans는 파일마다 순차 실행(팬아웃 LOCAL, 일부 실패 허용) · 원본 동작 보존, 슬롯 1개 · phase2.md §4.3, §6.8, A-2
- 2026-10-08 · ② 큐레이션 결과가 ③-1 기본 입력(`curation_id`), ① 결과(파라미터 정의·DOE 샘플·run 응답)로 ④ 파라미터 세트 자동 생성(1차 폴더 등록 유지) · 단계 연결 · phase2.md §6.8, §6.13
- 2026-10-08 · ⑤는 원본 RUN_CONFIG 키 전부로 `INPUT_HST_RUN.json` 생성 후 `cmd /c hstpy.bat 런처`(env ALTAIR_HOME, EDS_TNS_ACTVN_CHCKPT=1), 진행 = `Started run (N)`/MAX_DESIGNS(DOE는 미상), 결과 요약은 플러그형 + 파일 목록, Final 모델 기본 · 원본 인용, 결과 형식 미확인 · phase2.md §6.12, U28·U29
- 2026-10-08 · (가정) ⑤ 최적화 step은 오류 정규식을 적용하지 않고 종료코드만 판정 · 원본 동작, 실패 평가 무시 설정 · phase2.md A-8
- 2026-10-08 · SPDM은 `storage.spdm_roots` 하위 h3d·T01만 Study `02_import/`로 **복사**(하드링크 금지), SPDM 쓰기 0, 공백 있는 이름은 복사본에서 정리. 대시보드 "AI 학습 데이터로 보내기"는 딥링크 `/physicsai/import?spdm_path=…`(대시보드 측 요구 D8), 링크 열기만으로는 작업 생성 안 함 · SPDM 원본 보호 · phase2.md §6.11, §12.7, §13.3
- 2026-10-08 · (가정) 2차 템플릿·자원 설정은 비어 있어도 설정 오류가 아니라 해당 기능만 비활성("관리자 설정 필요") · 1차만 쓰는 설치 보호, 원본 파일 일부 미반입 · phase2.md §8.1, A-11, U19
- 2026-10-08 · (가정) Windows 배포의 서비스 등록은 작업 스케줄러(Register-ScheduledTask, 부팅 시작·재시작·실행 시간 한도 0), NSSM·pywin32 미사용. 배포 스크립트는 `deploy/`(Impl-Backend 소유), 실제 Windows 실행은 미검증 · 추가 의존성 없음 · phase2.md §11, A-14, U31
- 2026-10-08 · 알림 이벤트 `HPC_PARTIAL_FAILED`·`ENV_CHECK_DONE` 추가, ①②⑤ 완료/실패는 기존 이벤트에 작업 표시명, 대기열에 단계 배지·PBS run 집계 표시 · 장시간 작업 인지 · phase2.md §7.3, §12.9
