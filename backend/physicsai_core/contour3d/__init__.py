"""결과 3D 컨투어 변환(geometry-view.md §13.4, GV-C5 → contour3d-field.md): hw TCL 추출 CSV → `contour.glb`(+`contour_lod.glb`) +
`contour_frames.bin`(+`contour_disp.bin`) + `contour_manifest.json`(schema 2).

변환(convert·glb·meshopt·lod)은 numpy 배열 기반이고 워커 전용 import다(API 프로세스는 settings만 쓴다). 새 의존·paicad import 금지,
GLB writer는 형상 엔진과 코드를 공유하지 않는 자체 구현이다(독립 유지).
- settings: extract_settings.tcl 본문·extract_result.txt 해석·캐시 키·한국어 문구
- glb: glTF 2.0 바이너리(KHR_mesh_quantization 위치, `_NODE_ID`·`_SRC`, EXT_meshopt_compression 선택)
- meshopt: meshopt vertex·index sequence 인코더(numpy)와 시험용 참조 디코더, 위치 양자화
- lod: 피크 보존 대표 원 노드 격자 군집
- convert: CSV 스트리밍·외부 면(대체 경로)·Morton 정점 순서·프레임 uint16 양자화·크기 판정·manifest
- fixture: 프런트 V-C3F-8 픽스처 생성
"""
