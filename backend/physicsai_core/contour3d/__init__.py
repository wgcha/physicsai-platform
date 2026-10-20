"""결과 3D 컨투어 변환(geometry-view.md §13.4): hw TCL 추출 CSV → `contour.glb` + `contour_frames.bin` + `contour_manifest.json`.

플랫폼 워커 안 순수 Python(표준 라이브러리 struct·array·json·math만, 새 의존·paicad import 금지). GLB writer는 형상 엔진과 코드를
공유하지 않는 자체 작은 구현이다(독립 유지).
- settings: extract_settings.tcl 본문·extract_result.txt 해석·캐시 키·한국어 문구
- glb: glTF 2.0 바이너리(노드 1 = 정점 1, `_NODE_ID`)
- convert: CSV 검증·외부 면(대체 경로)·프레임 샘플링·상한 처리·manifest
"""
