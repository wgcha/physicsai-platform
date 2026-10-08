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
