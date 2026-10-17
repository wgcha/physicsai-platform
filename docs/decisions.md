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

## 2026-10-08 (2차 구현 — Impl-Backend 변경 메모 C1~C19 중 결정 성격 항목)

- 2026-10-08 · (메인 결정) `/studies/{id}`의 `stage_status`에 "1"·"2"·"5" 키 추가(각 단계 최근 작업, "3"·"4"와 같은 모양) · 스텝퍼 ①②⑤ 상태 표시 · phase2.md C15
- 2026-10-08 · (가정) migration 0001은 1차 스키마 동결본으로 만들고 이후는 명시적 DDL(0002·0003) · 0001이 현재 메타데이터를 쓰면 2차 테이블이 중복 생성 · phase2.md C1
- 2026-10-08 · (가정) `Dataset.curation_id`는 컬럼 없이 작업 params에서 계산, `curation_id` 지정 시 입력 경로를 큐레이션 출력으로 확정 기록 · 계약 §5.8에 datasets 변경 없음 · phase2.md C2
- 2026-10-08 · (가정) ①→④ 자동 생성 시 `eps_mesh*` starter 형태 파일은 조립 폴더에서 제외 · 1차 검증기 starter 1개 규칙과 원본 ⑤ 동작 · phase2.md C3
- 2026-10-08 · (가정) 서버 확정 기록 params 키(doe_id·curation_id·import_id·optimization_id 등)와 엔터티 행 생성 시점 · 재시도 재현성(B8) · phase2.md C5
- 2026-10-08 · (가정) 업데이트 스크립트의 "실행 중 작업" 확인은 토큰이 없으면 DB 직접 조회, 진행 중 환경 점검도 포함. 역할 생성 시 세션 로그 끄기 · `/queue` 인증 필요, 비밀번호 서버 로그 방지 · phase2.md C7
- 2026-10-08 · (가정) 오류 묶음·환경 점검 출력 마스킹은 계약 규칙 + 비밀 환경변수 값(원문·JSON 이스케이프)까지 · 로그에 URL 전체가 찍히는 경우 · phase2.md C12
- 2026-10-08 · (가정) 결과 폴더 run 매칭은 run_key 그룹만 대소문자 무시, 중복 폴더 run은 제외+경고(전부 중복이면 실패) · 오매칭 방지 · phase2.md C13
- 2026-10-08 · (가정) Altair 결과 이름 필드(DataType·Component·Layer·Request·곡선)는 허용 문자 화이트리스트 · TCL·cfg 주입 방지 · phase2.md C16
- 2026-10-08 · (가정) SPDM 복사는 스캔 기록(inode·크기·mtime)과 열린 파일 대조, O_NOFOLLOW. Windows는 reparse 검사+핸들 대조(상위 폴더 경합 한계 기록) · SPDM 링크 교체 TOCTOU · phase2.md C17
- 2026-10-08 · (가정) PBS 취소 명령 실패 시 작업을 CANCELED로 끝내지 않고 WAITING_HPC+주의 코드·알림 `HPC_CANCEL_FAILED`, 폴러가 재시도(migration 0003) · PBS 쪽 해석이 계속 도는데 취소된 것처럼 보이지 않게 · phase2.md C18
- 2026-10-08 · XML DOCTYPE·ENTITY 거부는 파서 수준(인코딩 무관) · 보안 §15.3 · phase2.md C19
- 2026-10-09 · 예측 결과 웹 3D 뷰어(컨투어·3D 모델) 보류 — 진행 안 함 · 모델이 커서 브라우저 부담(사용자 결정). 결과는 원본 TCL 이미지(A안) 유지
- 2026-10-09 · 운영 준비 범위: CI(Linux+Windows), 시연 모드(fake tools 배포판), 관리자·사용자 매뉴얼만 진행. 대시보드 연동·용량 정리·모델 비교·main 병합은 보류 · 사용자 결정

## 2026-10-11 (3차 진행 — 2026-10-09 보류 결정 일부 번복)

- 2026-10-11 · 3차(S1 재시도·보관·이름변경, S2 모델 비교, S3 용량·정리, S4 `simdash_adapters` 분리) 진행 — 2026-10-09 "용량 정리·모델 비교 보류" 결정을 **번복(대체)** · 사용자 지시 "지금 구현 가능한 것 모두" · phase3.md §1
- 2026-10-11 · (메인 결정·가정) 대시보드 연동은 `simulation_workbench` main에서 새 브랜치로 진행, 병합하지 않음 · 대시보드 운영 코드 보호, 2026-10-09 "main 병합 보류" 유지 · phase3.md
- 2026-10-11 · (메인 승인) AGENTS.md 역할 표 `packages/**`·`.github/**` → Impl-Backend · 어댑터 패키지·CI가 백엔드 시험·배포와 함께 바뀜 · phase3.md A3-8, D3-17
- 2026-10-11 · 정리(`STUDY_CLEANUP`) 실행 중에는 스캔 생성·`PUT /studies/{id}/final-model`도 409 `STUDY_CLEANUP_RUNNING`(R3-4의 스캔 예외 폐지) · 이동 중 스캔 결과·Final 보호 대상이 바뀌는 경합 차단 · phase3.md R3-4, D3-24
- 2026-10-11 · 작업 생성·재시도는 Study 행 `SELECT … FOR UPDATE` 후 gate·사전조건·삽입을 한 트랜잭션에서 · 같은 Study 동시 생성 직렬화 · phase3.md D3-25
- 2026-10-11 · 정리 사전조건 검사 순서(최신 성공 스캔 → 부분 스캔 → 비종료 작업 → 낡음 → 항목 합계), 관리 두 유형은 재시도 불가(`JOB_NOT_RETRYABLE`, 새로 실행) · 오류 문구 결정성·재현성 · phase3.md D3-9
- 2026-10-11 · 정리 대상은 DB 행이 가리키는 경로만(고아 폴더 제외), Final 평가 묶음·유형별 최신 성공 미리보기 보존, 링크 든 항목 제외 · 사용자 산출물 보호 · phase3.md D3-11
- 2026-10-11 · 정리 이동은 항목 단위: 링크·Study 밖·잠김·변경·없음은 작업 실패가 아니라 그 항목만 건너뜀, `PACKAGE_PSDATA`의 `package_rel=NULL`은 이동 직후 기록, 취소 시 옮긴 항목으로 매니페스트 기록 · DB·파일 일치, 삭제 호출 금지 · phase3.md D3-12, D3-22, D3-23
- 2026-10-11 · `CleanupSkip` 응답은 `rel`·`reason`(한국어 문구)만, 사유 코드는 노출하지 않음(코드는 `jobs.result`·매니페스트에만) · openapi 불변, 사용자에게는 문구로 충분 · phase3.md D3-22
- 2026-10-11 · `study.json` 갱신은 무작위 임시 파일 + `os.replace` 원자적 쓰기, 대상·폴더 링크 거부, 폴더 없으면 만들지 않음(이름 변경은 200 + WARNING) · 링크 경유 쓰기·폴더 재생성 방지 · phase3.md D3-20, D3-21
- 2026-10-11 · `simdash-adapters`는 PyPI에서 받지 않는다: `deploy/requirements.lock`(PyPI 외부 의존성만)과 `deploy/requirements.local.lock`(로컬 wheel 고정, `--no-index` 확인) 분리, 개발 설치는 `scripts/dev-setup`(패키지 먼저) · PyPI 이름 선점 공격 차단 · phase3.md §6.5, D3-17, D3-27
- 2026-10-11 · 어댑터 분리는 동작 불변: 플랫폼 `physicsai_core.hpc.*`가 패키지 객체를 같은 객체로 재노출(문구 골든 동일), 패키지는 표준 라이브러리만 import · 기존 호출처·시험 무수정 · phase3.md D3-15, D3-16, D3-26
- 2026-10-13 · 실행 환경을 대시보드와 동일하게: PG18 같은 인스턴스 별도 DB, Python 3.12.13, Node 22.23.2 — 사용자 결정 · `deploy.json` `dashboard_root`(선택)로 대시보드 `.env`의 `POSTGRES_BIN`·`DATABASE_URL` host·port와 `.tools` 고정 Python을 기본값으로(비밀번호 미독취), install은 Python≠3.12 중단·PG≠18 경고 · admin.md §2.1·§2.3·§14
- 2026-10-14 · 플랫폼 UI를 스위스 타이포그래피 격자로 전환(12열·행 176px·1px 선, 글자 역할 4단계, IBM Plex Sans/KR npm 번들), 강조색은 빨강 1개(현재 단계·Final 모델·주요 차트 선·포커스), 대시보드에는 적용하지 않음 — 사용자 결정 · 동작·API·문구 불변, 레이아웃·스타일만 · docs/design/swiss-grid-mockup.html, architecture.md §1.5
- 2026-10-15 · 운영 접속은 대시보드 Vite 프록시: `http://<대시보드>/physicsai/` → 127.0.0.1:8100, 백엔드가 `server.frontend_root` 정적 서빙, Caddy는 대안 — 운영 대시보드(scx-drive)가 Caddy 없이 Vite로 서비스하기 때문 · 대시보드 PR #53, phase3.md D3-28
- 2026-10-15 · 대시보드→PhysicsAI 학습 데이터 내보내기 보류, ① 형상 DOE→입력→드라이브·SDK 제출→h3d 회수는 플랫폼 안에서 — 사용자 결정 · 대시보드 연동은 링크·같은 주소만
- 2026-10-15 · 시연 우선순위 ④ 예측: 원본 기준 SimLab(m_1)→HyperMesh include(m_2)→edspy 체인 일치화, 원본 단독 예측을 "준비된 입력" 모드로 추가, edspy 성공 = h3d 존재(원본 ⑤) · phase3.md §11, D3-29~38
- 2026-10-15 · 빌드된 화면(`frontend-dist/`, `BUILD_INFO.json` source_hash)을 저장소에 포함 — 서버 설치·업데이트는 해시가 맞으면 Node·npm 없이 배치, `update-repo.ps1`이 스스로 `git pull --ff-only`(원클릭) — 사용자 결정("호환성 높게, 원클릭, 경로 지정 없음")·사내 보안 정책(`.bat` 차단, esbuild spawn EPERM) · phase3.md D3-40
- 2026-10-15 · 설치·업데이트에서 관리자 권한 제거 — 머신 환경변수 대신 런타임 파일(`.runtime\secrets\database_url`, ACL 현재 사용자·SYSTEM), 작업은 현재 사용자 Interactive·Limited + `--runtime` 인자, 이전 설치는 첫 한 번만 관리자 실행 — 사용자 결정·사내 보안 정책(대시보드도 일반 권한) · phase3.md D3-41
- 2026-10-16 · 모델 등록 시 `.pscfg`는 선택(0~1개, 2개 이상은 오류), `models.pscfg_*` NULL 허용(migration 0005), `{model_pscfg}` 템플릿 + pscfg 없는 모델은 작업 생성 409 `PSCFG_REQUIRED` — 사용자 결정 · 원본 예측·평가·최적화 명령에 pscfg 인자 없음(U7) · phase3.md D3-43
- 2026-10-16 · 다른 PC의 입력은 서버 공유 `physicsai-inbox`(쓰기)에 복사하고 `physicsai-data`(AI 루트, 읽기 전용)로 결과를 본다, 화면은 서버 경로 "찾아보기"로 고름(업로드 없음) — 사용자 결정 · phase3.md §12, D3-46
- 2026-10-16 · 파라미터 세트는 프로젝트 폴더 1개에서 자동 구성(tpl·CAD·조립 폴더, 등록 사본만 CAD 경로 `./<CAD>`), 세트 이름(label, migration 0006) — 사용자 요청 · phase3.md §13, D3-47
- 2026-10-16 · ④ 입력 방식 3개(템플릿 값 입력·일괄 예측(DOE)·준비된 입력): 템플릿 종류 mesh_only|assembly, 일괄 예측 = 부모 `PREDICT_BATCH`(플랫폼 동시 실행기로 m_1~m_3) + run별 하위 `PREDICT`(prepared), 응답 추출은 원본 ⑤ m_4 TCL(실패는 경고), 배치 갱신은 종료 훅 `job_end.batch_on_job_end` 하나로(migration 0007) — 사용자 결정 · phase3.md §14, D3-49·D3-51
- 2026-10-16 · 예측 끝에 HyperView 배치로 방향별 컨투어 PNG·동영상 저장(실패는 경고만), 재캡처는 별도 `CONTOUR_RECAPTURE`(원래 result 불변·조회 때 덮어쓰기), 파일 제공은 `/artifacts/{id}/media`(Range)(migration 0008) — 사용자 결정 · phase3.md §15, D3-52
- 2026-10-17 · PhysicsAI 화면 톤앤매너를 대시보드(simdashboard)와 통일(색 토큰 다크·라이트 그대로·Pretendard npm 번들·카드형 12열), 테마는 대시보드 localStorage(`simdashboard.workspace.theme.v1` → 레거시 `vd-workbench-theme` → dark)를 읽고 `storage` 이벤트로 따라감, 레이아웃 A(우측 고정 열 제거 → 상단 상태 칩 2개 + 오른쪽 서랍, 모델 목록은 ③) — 사용자 결정 · 2026-10-14 스위스 격자 결정("대시보드에는 적용하지 않음")을 대체 · architecture.md §1.5, phase3.md D3-55
- 2026-10-17 · 단계 버튼 ①~⑤ 전체 폭(5등분)·높이 확대(52px·15px)·번호 배지(원 문자 대신 숫자 1~5), "Study 관리"는 같은 줄 오른쪽 끝 작은 버튼 — 근거: 사용자 요청 · phase3.md D3-56
- 2026-10-17 · SCX 잡 제출(①·④ `hpc.gateway=scx`)은 대시보드 relay 경유(토큰 공유, PhysicsAI는 어댑터 미실행), 드라이브 /Users/vd.dashboard/<프로젝트>/<잡 폴더>(항상 새 폴더·삭제 없음·SPDM 루트 쓰기 금지), 결과 모름(SUBMISSION_UNKNOWN)은 자동 재제출·자동 취소 없이 사용자 확인 — 근거: 사용자 결정 · phase3.md §16, D3-57, contracts/scx_relay.md
- 2026-10-17 · SCX 잡 화면(①-4 run 표·④ 검증 해석): `/status.hpc.mode=scx`일 때만 드라이브 잡 폴더(표시·복사)·게이트웨이 중립 단계(업로드 중→대기→실행→완료→결과 회수), 결과 모름은 "확인 필요" 배지 + 조치 3개(다시 확인·잡 ID 연결·제출 안 됨으로 처리=중복 해석 경고 확인 대화상자), ④ 버튼 "검증 해석(SCX)" — 근거: phase3 §16.5 후속 프런트(필수 요소만) · phase3.md D3-58
- 2026-10-17 · ④ 일괄 예측 결과에 "설계공간 지도" 탭(PLS 기본·PCA·평행 좌표, 변수 z-점수, 축 설명 분산 %, 바이플롯, 연속 색 막대, 표·커브 선택 연동) — run별 대표값(커브 max·min·|max|, RESP _MIN·_MAX)은 백엔드 API(`design-map`, 파일 LRU)에서, PCA·PLS는 프런트에서 계산(새 DB·새 의존성 없음) — 근거: 사용자 결정 · contracts/s12_s13.md §17, D3-59
- 2026-10-17 · ⑤에 "플랫폼 내장(쿠션만 가능)" 모드 추가: ④ 일괄 예측 체인으로 탐색 → GP/RBF 대리모델 → 후보 k개 실제 예측 검증 반복(기본 3회 × 4), mesh_only·assembly 모두, 반복은 종료 훅 연쇄(`SURROGATE_OPT`, migration 0010) — 근거: 사용자 결정 · contracts/s12_s13.md §18, D3-60
- 2026-10-17 · 원본 최적화는 mesh_only 템플릿이면 생성·재시도 409 `TEMPLATE_ASSEMBLY_REQUIRED` + 워커 op_prep 가드(이슈 #4 TypeError 제거) — 근거: 사용자 결정 · contracts/s12_s13.md §18.8, D3-60
- 2026-10-17 · (사용자 확인 필요) 내장 최적화용 새 런타임 의존성 numpy·scipy(약 55 MB wheel, 워커 계산 모듈에서만 import, 없으면 기능만 꺼짐) — 근거: GP 우도 최적화·정수 변수 전역 탐색을 직접 구현하지 않기 위함 · contracts/s12_s13.md §18.2

## 2026-10-17 (native 형상 엔진 R1 모핑 — Plan 계약, contracts/geometry-engine.md)

- 2026-10-17 NX·SimLab·HyperMesh 없이 동작하는 native 형상 엔진은 R1 모핑(조립 폴더 기준본 `104_replace_node_elem.inc`의 노드·요소 ID·연결·요소 수 고정, `/NODE` 좌표만 변경, renumber·메셔 불사용, 출력 inc 이름·형식 동일 → 기존 `assemble_into` 그대로) — 근거: 사용자 합의, tie·RBE 노드 참조 유지 · geometry-engine.md GE-1
- 2026-10-17 1차 범위는 쿠션 솔리드 tetra4·위상 불변만, 쉘(형상 모핑·`/PROP/SHELL` 두께)과 mesh_only·원본 HyperStudy 최적화는 제외 — 근거: 사용자 합의 · geometry-engine.md §1.3
- 2026-10-17 엔진은 별도 프로세스 CLI `paicad`(packages/paicad, 하위명령 version·extract·tag·update·morph·check·run), 플랫폼은 `commands.paicad_*` argv 템플릿 + `TEMPLATE_SPECS` placeholder(`{paicad}` = `geometry.paicad_path`)로만 호출하고 성공은 출력 파일·보고 JSON으로 판정, 플랫폼 프로세스는 paicad·OCP를 import하지 않음 — 근거: 사용자 합의, 기존 외부 도구 규약·pyd 격리 원칙과 같음 · geometry-engine.md GE-2, §5
- 2026-10-17 기존 job_type·step 키를 유지하고 핸들러가 엔진으로 분기, 새 job_type은 ④ native 세트 준비 `PARAM_SET_NATIVE` 1개 — 근거: ②③⑤·배치 종료 훅·재시도·정리 범주 무수정 · geometry-engine.md GE-3, §7.3
- 2026-10-17 파라미터 계약은 `parameter_extracted.xml`(Root/Model/Parameter/Name,Value) 호환 + `parameter_features.json`(타입·면 서명·기준면·공칭·가능 범위·그룹) + 피처별 하이라이트 PNG, 범위 기본 ±5% — 근거: 사용자 합의, ①-1 TX_PARSE 재사용 · geometry-engine.md GE-4, §4.3
- 2026-10-17 검사(파라미터 재측정·경계 편차·품질·간섭·tie) 실패 시 샘플 스킵 + 사유 코드 `GEOM_*`(CAD 생성 불가/간섭/품질 미달/편차 초과/tie 투영 실패)를 DOE·배치 run에 기록 — 근거: 사용자 합의 · geometry-engine.md GE-5, §6.5
- 2026-10-17 엔진 선택은 `geometry.engine`(altair|native) 기본값 → `param_sets`·`train_setups`·`train_does.engine`에 생성 시 확정, 데이터셋·모델도 엔진 기록, 혼용은 422 `ENGINE_MIXED`·409 `ENGINE_MISMATCH`(migration 0012) — 근거: 사용자 합의(혼용 금지) · geometry-engine.md GE-6, §7.5·§7.7
- 2026-10-17 검사 기준 고급 옵션(품질·간섭·편차 허용오차)은 기본값 `geometry.defaults`, 세트별 덮어쓰기 `param_sets.geom_options`, 사용값은 run 폴더 `options.json`, UI는 접힘 1개 — 근거: 사용자 합의 · geometry-engine.md GE-7, §4.9·§8
- 2026-10-17 (확정 대기) 두께 변경 기준면 = 제품·타 바디 접촉면 고정·반대 면 이동, 동률이면 면적 큰 면 고정 — 근거: 사용자 합의(기본 규칙, 확정 대기) · geometry-engine.md GE-8, §15 Q2
- 2026-10-17 native DOE(①-3·④ 일괄)는 플랫폼 LHS(`batch_matrix`) + 동시 실행기, run 폴더 `run__N/{m_1,m_2,m_3}`·paramitem(`m_1/native_params.xml`) 호환으로 ②③ glob 유지 — 근거: 사용자 합의 · geometry-engine.md §7.3.3·§7.3.6
- 2026-10-17 (사용자 확인 필요) 새 런타임 의존성 cadquery-ocp(Windows cp312 wheel, paicad 프로세스에서만) + 기존 numpy·scipy, 오프라인 묶음(`collect-offline`)에 포함 — 근거: OCCT push/pull·투영을 직접 구현하지 않기 위함 · geometry-engine.md GE-10, §7.8
- 2026-10-17 native는 기존 Altair 경로와 외부 인터페이스(출력 파일 이름·폴더 레이아웃·XML 호환·m_3 조립 입력)만 같은 신규 별도 모듈이며, 기존 코드는 리팩터링하지 않고 `engine == "native"` 분기 지점만 최소 변경, altair 경로 동작·기본값·출력 불변 — 근거: 사용자 결정 · geometry-engine.md GE-11, §1.4·§16
- 2026-10-17 paicad는 SemVer(0.1.0부터, 단일 출처 `__version__`·pyproject 동적 참조), `packages/paicad` 변경 커밋마다 버전 올림 + CHANGELOG 항목(MINOR = 결과가 달라질 수 있는 변경, PATCH = 결과 불변), JSON `schema_version`은 엔진 버전과 별도, 모든 native JSON·옵션 사용값·DB(`engine_version`)에 사용 버전 기록(include에는 버전 주석 불허), 같은 native 데이터셋의 MINOR 혼재는 경고(확정 대기), 플랫폼 native 분기는 플랫폼 버전을 따르고 변경 시 이 문서에 기록 — 근거: 사용자 결정(재현성·데이터셋 추적) · geometry-engine.md GE-12, §17
- 2026-10-17 쉘 두께 파라미터를 이번 범위에 포함(별도 단계 3S, 단계 3과 병행, CAD 불필요): 조립 폴더 `/PROP/TYPE1` 두께만(TYPE9/10/11은 '미지원' 표시), `paicad props scan`으로 발견·±5%·extract 결과와 한 파라미터 표(XML 호환), run INPUT 복사본에서 고정폭 보존 교체(원본·SPDM 불변), 두께만 있는 param_set 허용, 실패 `PROP_OVERRIDDEN_BY_ELEMENT`·`PROP_THICKNESS_INVALID`·공유 PROP 경고, Igap·Δt·질량 영향 리스크, altair 적용 미결 — 근거: 사용자 결정 · geometry-engine.md §11.1·§6.5·§15 Q4·Q13
- 2026-10-17 (아래 항목 직후 항목으로 대체됨 — 재메시 비범위) 모핑 실패 시 재메시 폴백은 조건부 후속 옵션(1차 미구현, 1차는 스킵 유지): ID 참조 스캐너가 쿠션 component의 tie/RBE/집합 참조 0건일 때만, `remesh/` 저장 → renumber → 범위 초과 시 `ID_RANGE_OVERFLOW`, run 메타 `mesh_origin: morph|remesh`·데이터셋 혼재 경고, 메셔는 그때 결정 — 근거: 사용자 결정 · geometry-engine.md §11.2
- 2026-10-17 재메시 폴백은 비범위로 되돌림(`ID_RANGE_OVERFLOW`·`mesh_origin` 삭제), 대신 단계 2에 모핑 한계 측정 `paicad morph --sweep`(파라미터별 1D 스윕 → envelope.json/csv, `feasible` 반영·범위 초과 UI 경고(비차단), G1 envelope 보고서로 재메시 필요성 판단) — 근거: 사용자 결정, 모핑 성능 한계를 아직 모름(위 재메시 항목을 대체) · geometry-engine.md §11.2, V-GE-16
- 2026-10-17 paicad는 향후 독립 플랫폼 분리를 염두에 두고 개발(지금은 플랫폼 내 엔진): 플랫폼 import·DB·platform.yaml 읽기 금지, 플랫폼 고유 파일명·경로는 CLI 인자·JSON으로만, 경계 = 파일+CLI+버전 JSON, 솔버 writer 레지스트리(1차 Radioss만, LS-DYNA·Abaqus 비범위), paicad 메시지는 실패 코드+영문(한국어는 플랫폼 매핑), 패키지 자립(자체 pyproject·단독 pytest·CHANGELOG·제3자 라이선스 고지), 검사 V-GE-13·14; 분리 검토 기준 = 쿠션 외 2종 이상 검증 / 타 조직 외부 사용 요청 / 솔버 2종 이상 — 근거: 사용자 결정 · geometry-engine.md §18
- 2026-10-17 다중 baseline을 고급 옵션(접힘, 기본 단일·기존 흐름 불변)으로 추가, 단계 4B(4 이후·envelope 결과 확인 후 착수): 위상 변형(리브 수)·범위 분할을 `baselines/<id>/`+`param_map.json` 한 구조로, `paicad map`이 피처 대응으로 공통 변수명 자동 매칭(사용자 수정·N/A·`PARAM_NAME_CONFLICT`), 위상은 범주형 `baseline`, 배정은 공칭 최근접+`feasible` 이내·못 덮으면 `BASELINE_NO_COVER` 스킵, baseline별 층화 LHS·데이터셋 1개·run 메타 `baseline_id` — 근거: 사용자 결정(단일 baseline 모핑 한계 초과 범위 대응, 재메시 비범위 유지) · geometry-engine.md GE-13, §11.4, §7.3.8, V-GE-17·18
- 2026-10-17 다중 baseline 세부 확정: 새 job_type `PARAM_BASELINE_NATIVE` 없이 `PARAM_SET_NATIVE`에 매핑 단계 `BL_MAP` 추가(단일이면 SKIPPED, GE-3 예외 제거), 한 세트에서 위상 변형·범위 분할 혼합 비범위, N/A 변수 = 결측 지시 열 + 0 대체(Q14), 매칭 = 하드 게이트(타입·component·축 ≤10°) + 점수 S(0.35 위치·0.30 치수·0.15 방향·0.20 인접 Jaccard, σ=0.1) + 헝가리안, 임계 0.7/0.5(`MAP_LOW_SCORE`), 대칭 그룹 단위, 옵션 변경 가능(Q15), `baseline_id` DB 열 없음·run 메타만(Q16) — 근거: 사용자 결정 · geometry-engine.md §7.3.4·§7.3.8·§11.4·§15 Q14~Q16
- 2026-10-17 다중 baseline 자동 매칭은 초안 제시만(점수 무관 자동 확정 없음): `param_map.json` `status: draft|confirmed`(+`confirmed_by`·`confirmed_at`)·행별 `proposed`(엔진 제안)/`decision`(사용자 결정) 분리, 점수 구간 0.7/0.5는 판정이 아닌 표시 등급(추천/확인 필요(`MAP_LOW_SCORE` 유지)/미매칭 제안), UI 행별 수락·변경·분리 + [확정] 1개, 미확정 DOE·run 생성은 409 `PARAM_MAP_UNCONFIRMED`, baseline 추가·remap은 draft 복귀하되 피처 서명 같은 행의 결정은 승계 — 근거: 사용자 결정(오매칭이 DOE·학습 데이터에 조용히 섞이는 것 방지) · geometry-engine.md §4.10·§7.3.8·§11.4·V-GE-17·Q17
