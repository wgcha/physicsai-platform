# simdash-adapters 변경 기록

버전 정책(phase3.md §6.5): SemVer. 0.x 동안 공개 API(`simdash_adapters.__all__`) 모양 변경 = minor, 동작 수정·내부 변경 = patch.
`pyproject.toml`의 `version`과 `__version__`은 같아야 한다(시험 `tests/test_static.py`). 플랫폼은 루트 `pyproject.toml`에서 정확 버전으로 고정한다.

## 0.1.0 (2026-10-11)

- 최초 분리: `physicsai_core.hpc`(게이트웨이 프로토콜·command/none/adapter)와 회수 경로 해석(`map_path`, `resolve_collect_dirs`), 경로 문자열 규칙(`fwd`, `is_abs_path_str`)을 동작 그대로 옮김.
