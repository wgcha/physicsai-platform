"""native 형상 엔진(`paicad`) 플랫폼 쪽 순수 함수 모음(geometry-engine.md §7, 표준 라이브러리만).

플랫폼 프로세스(API·워커)는 `paicad`·OCP를 import하지 않는다(§1.4) — 외부 명령 결과 JSON·파일만 읽는다.
- options: 유효 옵션 병합·범위 검사(§4.9)
- reports: 보고 JSON 읽기(§7.2)
- messages: 실패 코드 → 한국어 문구·category(§6.5, §18.4)
- judge: 종료코드·보고·출력 파일 판정(§5.4)
- native_files: values.json·native_params.xml·doe_matrix.csv·SKIPPED.json(§4.4, §7.3.6)
- prep: 준비본 `native/` 경로·prep.json 유효성(§4.2, §17.3)
- features_view: parameter_features.json 요약(§7.6)
"""
