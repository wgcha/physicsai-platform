# AGENTS.md — 저장소 작업 규칙

계약: 1차 [docs/contracts/platform.md](docs/contracts/platform.md), 2차 [docs/contracts/phase2.md](docs/contracts/phase2.md)(2차가 바꾸는 1차 규칙은 phase2.md §2.3, 2차 문서 우선). 계약과 다르게 구현해야 하면 먼저 Plan에 계약 수정을 요청한다(해당 문서 끝 "변경 메모"에 기록).

## 역할 분리

| 역할 | 수정 가능 범위 |
|---|---|
| Plan | `docs/**`, `AGENTS.md`, `README.md` (애플리케이션 코드 작성 금지) |
| Impl-Backend | `pyproject.toml`, `backend/**`, `worker/**`, `migrations/**`, `config/**`, `scripts/**`, `deploy/**`, `.gitignore` |
| Impl-Frontend | `frontend/**` |
| Verifier | 수정 없음. platform.md §22(1차)와 phase2.md §20(2차, V2-*) 체크리스트로 판정하고 결과를 보고 |

- 남의 소유 파일은 고치지 말고 요청한다. API 모양 변경 순서: 계약 수정(Plan) → `backend/openapi.json` 갱신(Backend) → 프런트 반영.

## 필수

- **테스트 필수**: 기능 변경마다 자동 시험을 함께 넣는다. `scripts/test-all`이 Linux(Altair 없음, PostgreSQL 있음)에서 통과해야 완료. 실제 Altair가 필요한 동작은 가짜 도구(`backend/tests/fake_tools/`)로 시험하고, Windows 전용 시험의 skip은 통과로 치지 않는다.
- **하드코딩 금지**: Altair·PBS 실행 파일 경로, 명령 인자, AI 루트, 포트, 정규식은 `config`에서만 읽는다. 코드에 `Program Files` 경로 금지.
- **SPDM 보호**: SPDM master에 쓰지 않는다(2차 가져오기도 읽기·복사만, 하드링크 금지). 산출물은 AI 루트에만. 사용자 산출물은 삭제하지 않고 `_backup`으로 이동한다.
- **보안**: 외부 명령은 워커에서만, `shell=False` 인자 배열로. pickle(`.pscfg`)을 열지 않는다. 원본 pyd 코어를 플랫폼 프로세스에서 import하지 않는다(런처를 Altair 도구가 실행). 업로드 엔드포인트를 만들지 않는다. 대시보드 세션 토큰을 로그·DB에 남기지 않는다.
- DB에는 경로·상태·수치 요약만. 파일 본문 저장 금지.
- 사용자 표시 문구·오류 메시지는 한국어.

## 커밋 규칙

- 작은 단위로, 제목 한 줄(한국어 또는 영어, 72자 이내) + 필요 시 본문에 계약 절 번호(`platform.md §8.4`).
- 커밋 전 `scripts/test-all` 통과. 실패한 채로 커밋하지 않는다.
- 비밀값·`config/platform.yaml`·대용량 산출물(`*.psdata`, `*.psmdl`, `*.h3d`)을 커밋하지 않는다.
- 메인 에이전트가 지시하지 않으면 push하지 않는다.
