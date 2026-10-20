# S20 계약 — SCX Radioss 버전 작업별 입력(D3-68)

> 근거: 사용자 결정(2026-10-20) "버전은 사용자 입력이 좋아. 26.1이 디폴트". 이슈 #8 후속(SCX 연결 설정 중).
> 범위: ①-4 해석 제출(`TD_SOLVE`)과 ④ FEM 검증(`PREDICT_VERIFY`)의 SCX Radioss 제출. migration 없음, 새 job_type·라우트 없음.

## 1. 설정

- `hpc.scx.version` 기본값 `""` → **`"26.1"`**(스키마 한 곳, 예시 yaml·admin.md §16.3 동기화). 빈 문자열로 두면 기존처럼 필수 누락(검증 오류/configured=false) 그대로.
- `hpc.scx.appliance`는 그대로 필수(기본 `""`).

## 2. API

- 작업 params의 HPC 덮어쓰기에 `version` 추가:
  - `services/job_params/base.py` `HpcOverrides.version: str | None` (pattern `^[A-Za-z0-9][A-Za-z0-9 ._\-]{0,63}$`)
  - `schemas/fem_verify_req.py` `FvHpc.version: str | None` (같은 pattern)
  - null·누락 = 설정값(`hpc.scx.version`). 앞뒤 공백은 잘라 저장, 빈 문자열은 null로.
- `/status`의 `StatusHpc`에 `scx_version: str | None = None` 추가 — gateway `scx`일 때 설정의 `hpc.scx.version`, 아니면 null. 화면 기본값 표시용.
- `command` 모드(PBS)는 `version`을 쓰지 않는다 — 들어오면 작업 로그 1줄 "command 모드는 hpc.version을 쓰지 않습니다(무시)"(scx의 queue·walltime 무시와 같은 방식).

## 3. 워커

- `steps/_scx_submit.py` `build_request`: `version = (over.get("version") or cfg.version)`. 제출 기록(`staged.request`)에 실제 쓴 버전이 남는다(기존 `to_json`).

## 4. 화면(필수 입력 1칸씩, 새 버튼 없음)

- ① `stages/stage1/SolveCard.tsx`, ④ `stages/stage4/verify/VerifyNew.tsx`: HPC 입력 옆에 **"Radioss 버전"** 텍스트 칸 1개. gateway가 `scx`일 때만 보임.
  - 초기값 = `/status` `hpc.scx_version`(없으면 `"26.1"`). 사용자가 바꾸면 그 값을 `hpc.version`으로, 초기값 그대로면 null로 보낸다(설정 변경이 따라가도록).
  - pattern 위반이면 칸 아래 오류 "버전은 영문·숫자·공백·._- 64자 이내"이고 제출 버튼 비활성.
- 작업 상세의 HPC 행(있으면)에 쓴 버전을 표시하는 것은 **하지 않는다**(필수 아님 — 제출 기록 JSON에 남음).

## 5. 시험(V3-S20-*)

1. 설정 기본 `version == "26.1"`, 빈 문자열이면 기존 오류 그대로.
2. `HpcOverrides`·`FvHpc` version pattern 통과/거부 표, 공백 trim, 빈 문자열 → null.
3. 워커 `build_request`: params `hpc.version` 있으면 그 값, 없으면 설정값.
4. command 모드에 version → 무시 로그 1줄, 제출 인자 불변.
5. `/status.hpc.scx_version`: scx면 설정값, none·command면 null. openapi 갱신(operationId 불변).
6. 프런트: scx일 때만 칸 표시, 초기값 = scx_version, 그대로면 null 전송, 바꾸면 값 전송, 잘못된 값이면 버튼 비활성.
7. 회귀: `scripts/test-all.sh` 전체.

## 변경 메모

- D3-68(2026-10-20): SCX Radioss 버전을 작업별 입력으로(기본 `hpc.scx.version` = "26.1"). appliance는 설정 필수 유지.
- 구현 반영(2026-10-20): 프런트는 빈 칸을 오류로 본다(서버는 ""→null 유지). ①-4에서는 칸이 접힌 "고급" 절(queue·ncpus·walltime 옆)에 있고, 값이 틀리면 제출 버튼 옆에도 사유를 보인다.

## 보강 1(2026-10-20, 사용자 결정 — 이슈 #8 코멘트 4·5)

- `hpc.scx.mpi` 기본값 `"SMP (default)"` → **`"Pure MPI"`**(Radioss `-np`). 스키마 한 곳·예시 yaml·admin.md §16.3 동기화.
- 어댑터 허용 값 6개: `"SMP (default)"`, `"Pure MPI"`, `"Hybrid 2 Threads"`, `"Hybrid 4 Threads"`, `"Hybrid 8 Threads"`, `"auto"`. 목록 밖 값은 **설정 경고**(오류 아님 — 어댑터가 값을 늘릴 수 있음) "hpc.scx.mpi가 알려진 값이 아닙니다: <값>".
- 화면: gateway가 `scx`면 ①-4 "고급"의 queue·walltime 칸을 숨긴다(ncpus·Radioss 버전만). 숨긴 칸 값은 보내지 않는다(null).
- 시험 V3-S20-8: mpi 기본값, 목록 밖 값 경고 1건·목록 안 값 경고 없음, scx일 때 queue·walltime 칸 없음·PBS일 때 있음.
