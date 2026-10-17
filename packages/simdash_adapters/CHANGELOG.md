# simdash-adapters 변경 기록

버전 정책(phase3.md §6.5): SemVer. 0.x 동안 공개 API(`simdash_adapters.__all__`) 모양 변경 = minor, 동작 수정·내부 변경 = patch.
`pyproject.toml`의 `version`과 `__version__`은 같아야 한다(시험 `tests/test_static.py`). 플랫폼은 루트 `pyproject.toml`에서 정확 버전으로 고정한다.

## 미배포(같은 저장소, 버전 0.1.0 유지 — 올림은 Plan 결정 대기)

- scx 게이트웨이(phase3 §16, platform.md §12.5): `simdash_adapters.hpc.scx`(`ScxHpcGateway`·`ScxConfig`·`ScxRadiossRequest`·
  `ScxSubmitOutcome`·`validate_scx_config`·`read_secret_file`), `hpc.scx_client`(대시보드 relay HTTP 클라이언트 — `http.client`만),
  `hpc.scx_naming`(드라이브 이름·경로 규칙). 팩터리 `make_gateway("scx", scx=…, scx_secret_path=…, on_secret=…)`.
- 형식 확장(기본값 있음 — 기존 생성 코드 불변): `HpcAvailability.mode`에 `"scx"`, `HpcStatus.outcome·output_path·output_rel·error_message`,
  `HpcGatewayError(…, relay_code=, http_status=, retryable=, transport=)`, 오류 코드 `SUBMISSION_UNKNOWN`.
- 최상위 공개 API(`simdash_adapters.__all__`)는 그대로(새 이름은 `simdash_adapters.hpc`에서만). 허용 표준 라이브러리에 http·urllib·hashlib·json·
  fnmatch·unicodedata·time·threading 추가(시험 `tests/test_static.py`).

## 0.1.0 (2026-10-11)

- 최초 분리: `physicsai_core.hpc`(게이트웨이 프로토콜·command/none/adapter)와 회수 경로 해석(`map_path`, `resolve_collect_dirs`), 경로 문자열 규칙(`fwd`, `is_abs_path_str`)을 동작 그대로 옮김.
