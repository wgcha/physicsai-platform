# 계약: 결과 3D 컨투어 현장 보정 — 대형 모델(압축·LOD·상한)·캐시 키·부품 범위·대체 사유 (v0.2.10)

> 상태: **초안**(2026-10-23, Plan). 릴리스 **v0.2.10**. 기준: 60adb26(v0.2.9 배포본), migration HEAD `0023_doe_methods`. **migration `0024_contour3d_field`**(§5.6 artifact kind 제약 확장, 변경 메모 C3F-C1).
> 상위: [geometry-view.md](geometry-view.md) §7.1(프런트 의존)·§13(결과 3D 컨투어), [contour3d-default.md](contour3d-default.md)(④⑤⑥ 기본 3D 표시), [job-queues.md](job-queues.md) §6.1(수령·잠금). 충돌하면 이 문서가 우선한다. 범위는 아래에 적은 항목뿐이다.
> 근거: GitHub 이슈 #11(사용자 현장 실행, HyperView 26.1), 사용자 요구 "HOOPS처럼 브라우저 수준으로 압축", 코드 확인(60adb26), PyPI 조회(2026-10-23).
> ID 규칙: 결정은 `C3F-n`, 시험은 `V-C3F-n`, 변경 메모는 `C3F-Cn`으로 쓴다.

## 0. 한 줄 요약

쿠션 입력 예측 h3d는 쿠션 하나만으로 노드가 약 97만 개다. 이 규모를 브라우저에서 다루도록 다음을 바꾼다.
- **형상**: 양자화(`KHR_mesh_quantization`)와 `EXT_meshopt_compression`을 쓴다. three에 들어 있는 MeshoptDecoder로 풀고, 법선은 뷰어가 계산한다.
- **필드**: 프레임별 uint16 양자화. 스칼라와 변위를 다른 파일에 나누고, 변위는 변형 배율을 켤 때만 받는다.
- **전송**: 고정 크기 프레임 Range는 그대로 두고 HTTP 압축은 쓰지 않는다.
- **LOD**: 노드가 50만을 넘으면 피크를 보존하는 대표 원 노드 군집으로 표시용 저해상도 메시를 함께 만든다. 첫 표시와 조작(회전·재생) 중에는 저해상도를, 멈추면 전체 해상도를 보인다. 프레임별 극값 노드는 마커로 따로 보인다.
- 97만×50 기준 효과:
  - 형상: 51 MB → 약 10~15 MB
  - 프레임: 15.6 MB → 스칼라 1.9 MB(변위 5.8 MB는 필요할 때만)
  - 전체: 780 MB → 약 400 MB
  - 첫 표시: 100 Mbps에서 ≤ 2 s 목표
- 그 밖
  - 상한을 다시 정한다. 노드 200만, 형상 64 MiB, 스칼라 256 MiB, 변위 1 GiB, 프레임 55.
  - 캐시 키에 상한·부품 이름·추출 TCL 해시·변환기 버전 2를 넣는다.
  - 조립 결과는 표시 부품 이름으로 범위를 줄인다.
  - UNIT 오류 문구가 단위 자리에 들어가지 않게 한다. TCL을 단독으로 실행하면 안내 문구를 남긴다.
  - 변위가 없거나 조회에 실패하면 스칼라만으로 계속하고, 변형 배율 컨트롤을 숨긴다.
  - setup이 추출 TCL 경로를 채운다. PNG로 대체될 때는 사유를 한 줄로 보인다.
  - GPU 수령과 lease 해제 사이의 잠금 순서를 통일한다.

## 1. 현장 사실과 코드 근거

| # | 사실 | 근거 | 영향 |
|---|---|---|---|
| F1 | 대상은 쿠션 입력 예측 `…/04_predict/<id>/RESULT/EPS_mesh_0000_pred.h3d`이다. TCL(26.1)은 STATUS=OK, NODES=973060, FACES=610057, FRAMES_TOTAL=22, CornerStress/vonMises를 보고했다. FEM 결과는 50프레임이고, 현장은 `max_frames: 55`로 설정했다 | 이슈 #11 | 부품 이름으로는 줄일 수 없다. 압축·LOD·상한이 해결의 중심이다 |
| F2 | **NODES·FACES의 뜻**: 대체 경로(`elements.csv`)에서 `NODES`는 사용 노드 수(내부 노드 포함)이고 `FACES`는 요소 수다. 외부 면 노드 N_ext(≤ 973,060)는 C3_CONVERT가 계산한다 | TCL 172~188행 | 노드/요소 ≈ 1.6이므로 두께 방향 1~2층 헥사로 보인다. 설계는 최악값 97만을 기준으로 한다. 실측은 manifest `limits.nodes` |
| F3 | N_ext가 `max_nodes` 300,000을 넘으면 결과 FAIL `CONTOUR3D_TOO_LARGE`이고 이 결과가 캐시된다 | `convert.py:234`, `settings.py:31` | — |
| F4 | 캐시 키에 상한이 없어서 설정을 올려도 캐시된 FAIL이 돌아온다 | `settings.py:100`, `contour3d_api.py:159` | §7 |
| F5 | **숨은 실패**: `CONTOUR3D_GLB`를 내려받을 때 상한이 `ui.max_artifact_bytes`(20 MiB)다. 97만 노드 GLB(약 51 MB)는 413이 난다 | `services/contour_capture.py:148` | 새 키 `max_glb_bytes` |
| F6 | bin은 변위를 섞어 16N B/프레임이다. 상한을 넘으면 재샘플을 먼저 한다. 97만×50 = 780 MB(스칼라만 195 MB) | `convert.py:265-279` | 프레임 보존 우선으로 바꾼다(§5.4) |
| F7 | `UNIT=Invalid command syntax: "result scalar unit"`: 오류 문구가 단위 값으로 들어간다 | TCL 114행 | §9.2 |
| F8 | TCL을 단독 실행하면 19행 `source` 오류가 난다. 추출 폴더는 변환 뒤 지워져서 재현할 수 없다 | TCL 19행, 워커 131행 | §9.3 |
| F9 | `contour3d.enabled: false`가 기본이고 화면은 사유를 보이지 않는다. setup은 `contour_extract_tcl`을 채우지 않는다 | `setup_config.py:647-651`, `ContourSlot.tsx:37` | §11·§12 |
| F10 | 잠금 순서가 서로 반대다. `release`는 jobs → worker_slot, `claim_gpu` 만료 경로는 worker_slot → holder jobs | `job_lease_end.py:96-166`, `job_lease.py:65-77` | §13 |
| F11 | Python 의존: numpy·scipy는 이미 운영 의존이다(워커 지연 import). PyPI `meshoptimizer`는 알파 sdist만 있다(0.2.30a0, wheel 없음 — Windows 오프라인 빌드 불가). `meshopt` 0.1.1(제3자, 2026-10 첫 공개, cp312 win wheel 있음)은 신생이다. `fast-simplification` 0.2.0(pyvista, numpy만 의존, cp312 win wheel 있음)이 있다 | `pyproject.toml`, PyPI JSON | §6.3·§17 Q1 |
| F12 | 프런트: three 0.186.1에 `examples/jsm/libs/meshopt_decoder.module.js`(wasm을 JS 안에 내장, 외부 파일 없음)가 들어 있다. geometry-view §7.1은 디코더·외부 파일을 요구하는 모듈(DRACOLoader 등)과 웹 워커를 금지한다 | `frontend/package.json`, GV §7.1 | §4.2 |
| F13 | PhysicsAI 예측 h3d에는 변위 결과가 없을 수 있다. `INCLUDE_DISP=1`(기본)이면 변위 조회 실패가 catch에서 작업 전체를 `EXTRACT_ERROR`로 끝낸다. 수동 실행(`INCLUDE_DISP 0`)은 OK였다 | TCL 203~210행, 이슈 #11 | §9.4(스칼라만으로 계속) |

## 2. 결정 요약(C3F-1~C3F-18)

**확정(2026-10-23 사용자)**: §17 Q1 = 새 네이티브 Python 패키지 없이 numpy 직접 구현(격자 군집 LOD·자체 meshopt 인코더). Q2 = 새 설치에서만 HyperView 감지 시 `contour3d.enabled: true`, 기존 설정은 바꾸지 않고 권고 줄만 출력. 계약 상태: 확정.

| ID | 결정 |
|---|---|
| C3F-1 | 상한 기본값(§8): `max_nodes` 2,000,000 · `max_frames` 55 · 새 키 `max_glb_bytes` 64 MiB · `max_bin_bytes` 256 MiB(값은 지금과 같고 뜻이 "양자화 스칼라 파일"로 바뀜) · 새 키 `max_disp_bytes` 1 GiB · 새 키 `disp_max_nodes` 1,500,000 · 새 키 `lod_min_nodes` 500,000·`lod_target_vertices` 100,000 · 캐시 총량 4 GiB |
| C3F-2 | 형상 압축은 **meshopt**(`EXT_meshopt_compression` + `KHR_mesh_quantization`)로 한다. Draco는 기각한다(§4.1). 디코더는 three 동봉 `meshopt_decoder.module.js`이고 새 npm 의존은 없다 |
| C3F-3 | 정점 순서 = 프레임 레코드 순서(불변식). 변환기는 정점을 공간 순서(Morton)로 다시 배열할 수 있다. `_NODE_ID`는 UNSIGNED_INT로 무손실 보존한다. **NORMAL은 넣지 않고** 뷰어가 로드할 때 1회 계산한다(§4.3) |
| C3F-4 | meshopt 인코더는 **numpy로 직접 구현**(확장 명세의 비트스트림)하고, three 디코더 왕복 시험으로 검증한다. 준비 전에는 설정 `contour3d.meshopt: false`로 양자화만 쓴다(유효한 glTF, 디코더 불필요)(§4.4) |
| C3F-5 | 필드: 프레임별 uint16 양자화를 쓴다. 스칼라 65535 = NaN. 변위는 성분별 프레임 범위로 양자화한다. manifest에 프레임별 scale·offset을 넣는다. 오차 상한은 §5.2 |
| C3F-6 | 파일을 나눈다. `contour_frames.bin`(2N B/프레임) + `contour_disp.bin`(6N B/프레임, 선택, 배율 > 0일 때만 받음). manifest `schema_version` 2, `converter_version` 2. 뷰어는 schema 1·2를 모두 읽는다 |
| C3F-7 | 전송: 고정 크기 레코드 Range를 유지하고 **HTTP 압축은 쓰지 않는다**. 응답에 `Cache-Control: no-transform`을 붙인다. Caddy `encode`를 media 경로에 적용하지 않는다(§6) |
| C3F-8 | LOD: N_ext > `lod_min_nodes`이면 `contour_lod.glb`를 만든다. 방법은 **피크를 보존하는 대표 원 노드 격자 군집**(numpy, 법선 방향 버킷)이다. LOD 정점은 원 노드이고, 값은 전체 레코드에서 그대로 모은다(보간·평균 없음)(§7) |
| C3F-9 | 뷰어: 첫 표시와 조작(회전·확대·재생) 중에는 LOD를, 조작이 끝나고 250 ms 뒤 전체 해상도를 보인다. 프레임별 최대·최소 노드 마커와 값(정확 float)을 늘 보인다 |
| C3F-10 | 크기 우선순위: 형상 초과 → FAIL. **변위를 먼저 빼고**, 그래도 넘으면 스칼라를 재샘플(최소 2)한다. 변위 때문에 프레임을 줄이지 않는다 |
| C3F-11 | 캐시 키에 `comps`·`display.unit`·`limits`·`lod`·`meshopt`·`extract_tcl`(sha256 앞 16자)를 넣고 `converter_version` 2로 한다. 예전 행은 적중하지 않는다(§10) |
| C3F-12 | 결과 FAIL(결정적)은 같은 키에서 다시 만들지 않는다. [다시]는 작업 실패·취소에만 둔다. 같은 화면에서 실패 뒤 자동 재요청은 없다 |
| C3F-13 | 부품 범위: 표시 설정 `comps`를 `COMPS`로 넘긴다. 쿠션 입력 예측은 늘 비운다. 적용에 실패하면 전체를 추출하고 경고를 남긴다(FAIL 아님)(§9.5) |
| C3F-14 | UNIT: TCL은 조회하지 않는다(빈 값). 대신 표시 설정의 새 선택 키 `unit`을 쓰고, 오류 문구처럼 보이는 값은 버린다(§9.2) |
| C3F-15 | TCL 단독 실행: 안내 문구를 출력하고 종료한다. 결과 FAIL이면 설정 파일·결과 파일·TCL을 남긴다(CSV만 지움)(§9.3) |
| C3F-16 | 변환기는 numpy 배열 기반이다(1M 노드에서 피크 ≤ 1.5 GB). 프레임 CSV는 스트리밍으로 읽는다(§9.6). `physicsai_core/contour3d`에서 numpy를 허용한다(워커 전용 import, API 프로세스는 convert를 import하지 않음) |
| C3F-17 | setup_config는 `resources.contour_extract_tcl`을 git 경로로 채운다(빈 값만). `contour3d.enabled`는 Q2를 따른다(§11). 대체 표시 사유는 한 줄로 보인다(§12) |
| C3F-18 | 잠금 규칙: **`worker_slot`을 쥔 채 jobs 행을 기다리지 않는다.** `claim_gpu` 만료 경로의 holder 잠금은 `SKIP LOCKED`이고, 잠겨 있으면 이번 수령을 건너뛴다(§13) |
| C3F-19 | 변위가 없거나 조회에 실패하면 **스칼라만으로 계속**한다. 첫 프레임에서 한 번 판정하고, 이후 프레임과 헤더를 일관되게 처리한다. 결과 줄은 `DISP=NONE` + `DISP_REASON`, 경고는 `CONTOUR3D_DISP_UNAVAILABLE`이다. 뷰어는 변위가 없으면 변형 배율 컨트롤을 **숨긴다**(§9.4) |

## 3. 수치 목표 — 97만 노드·50프레임 쿠션

가정은 다음과 같다. 사무용 PC(내장 GPU)와 사내 LAN(1 Gbps ≈ 100 MB/s, 100 Mbps ≈ 11 MB/s). N = 973,060, 삼각형 T ≈ 1.95M. 압축 후 크기는 추정치(±50%)이고, V-C3F-16에서 실측해 이 표를 갱신한다.

| 항목 | v0.2.9(상한을 풀었다고 가정) | v0.2.10 | 비고 |
|---|---|---|---|
| 형상 GLB | 50.7 MB(위치·법선 12+12 B, `_NODE_ID` 4 B, 인덱스 uint32) | **10~15 MB**(양자화만 쓰면 약 31 MB) | 위치 int16×3(+패딩 8 B), 법선 없음, `_NODE_ID` 4 B, meshopt(ATTRIBUTES + INDICES) |
| LOD GLB | – | **약 1.5 MB**(정점 10만) | `_SRC`(원 정점 번호) 포함 |
| 프레임당 스칼라 | 3.9 MB(변위를 섞으면 15.6 MB) | **1.95 MB** | uint16 |
| 프레임당 변위 | (섞임) | **5.8 MB**(배율 > 0일 때만) | uint16×3 |
| 전체(50프레임) | 780 MB | **약 400 MB**(형상 15 + LOD 1.5 + 스칼라 97 + 변위 292) | 서버 캐시 |
| 첫 표시(LOD + 첫 프레임) | 66 MB 받은 뒤(100 Mbps 약 6 s + 파싱) | **≤ 2 s @100 Mbps**(3.5 MB + 디코드) | 목표 |
| 전체 해상도 전환 | – | **≤ 5 s @100 Mbps**(백그라운드) | 목표 |
| 프레임 전환(스칼라) | 1.4 s @100 Mbps | **≤ 0.3 s @100 Mbps** | 목표 |
| 브라우저 메모리(GPU 포함) | 약 200 MB 이상 | **≤ 250 MB**(전체 + LOD + 캐시 예산) | 목표 |

## 4. 형상 압축

### 4.1 meshopt와 Draco 비교

| 관점 | **meshopt**(EXT_meshopt_compression + KHR_mesh_quantization) | Draco(KHR_draco_mesh_compression) |
|---|---|---|
| 압축률 | 양자화 + 바이트 델타. 원본 대비 약 3~5배 | 더 좋다(약 1.5~2배 더 작음) |
| 디코드 속도 | 수 GB/s급(97만 정점 수십 ms, 주 스레드) | 수십~100 MB/s급(수백 ms~1 s). 사실상 웹 워커가 필요하다 |
| 배포 | three 동봉 `meshopt_decoder.module.js` 하나(wasm이 JS 안에 내장). 별도 파일·경로 설정 없음 | `draco_decoder.wasm`·`draco_wasm_wrapper.js`를 정적 경로로 배포해야 한다(`setDecoderPath`). GV §7.1 "외부 파일 요구 모듈·웹 워커 금지"에 걸린다 |
| 오프라인 | 문제 없음(외부 요청 0) | 파일을 함께 배포하면 가능하지만 빌드본 검사 규칙을 바꿔야 한다 |
| **정점 순서** | 보존된다(코덱이 순서를 바꾸지 않음) → 프레임 레코드와 바로 맞는다 | Edgebreaker가 정점 순서를 바꾼다 → 레코드 대응이 깨진다(순차 모드는 압축률이 떨어짐) |
| 사용자 속성 `_NODE_ID` | 무손실 ATTRIBUTES 모드 | generic 속성으로 가능하지만 양자화·순서 문제가 있다 |
| 서버 인코더 | 공개 비트스트림 명세 → numpy로 구현 가능(새 의존 없음). wheel 후보는 신생뿐(F11) | DracoPy(네이티브 wheel) 또는 `draco_encoder` 실행 파일이 필요하다 |

**권고: meshopt.** 정점 순서를 보존한다는 점이 결정적이다(프레임 레코드는 정점 순서 배열). 디코드가 빠르고, 파일 하나로 오프라인 배포가 끝난다. Draco가 압축률에서 앞서는 부분(수 MB)은 첫 표시에서 LOD가 메운다.

### 4.2 프런트 의존(GV §7.1 개정)

- 허용 모듈에 `three/examples/jsm/libs/meshopt_decoder.module.js`를 추가한다(three 패키지 안이라 새 npm 의존 없음). 사용은 `GLTFLoader.setMeshoptDecoder(MeshoptDecoder)`이고 주 스레드에서 돈다(웹 워커 금지 유지). `DRACOLoader` 금지도 유지한다.
- 빌드본 외부 URL 0건 검사(GV-C3)를 그대로 통과해야 한다. 디코더는 base64 wasm을 `WebAssembly.instantiate`하므로 fetch가 없다.
- 대시보드 사이트에 CSP가 있으면 `'wasm-unsafe-eval'`이 필요하다(현재 플랫폼은 CSP를 보내지 않음. 보고서 CSP는 다른 경로라 무관).
- 청크 크기 증가(디코더 약 20 KB 추정)를 GV 변경 메모에 기록한다.

### 4.3 GLB 내용(schema 2)

| 항목 | 규칙 |
|---|---|
| 메시 | 루트 `paicad_contour` 아래 `surface` 1개(TRIANGLES), `extras`는 §13.4와 같음 |
| 정점 순서 | **정점 i = 모든 프레임 레코드의 i번째 값**(불변식). 변환기는 정점을 양자화 좌표의 Morton 코드 순서(같으면 노드 ID 순)로 다시 배열한다(결정적). 압축률·국소성을 위해서이며 nodes.csv 순서 규칙(§13.4)을 대체한다 |
| POSITION | `KHR_mesh_quantization`: SHORT normalized ×3(+2 B 패딩, stride 8). 노드 `translation`·`scale`로 bbox를 복원. 위치 오차 ≤ 축별 bbox 길이 / 65534 / 2(1.5 m 부품 ≈ 0.011 mm). min·max 필수 |
| NORMAL | **넣지 않는다.** 뷰어가 로드 직후 변형 전 위치로 1회 계산한다(면적 가중, `computeVertexNormals`와 같음, 97만 정점 약 0.1 s). 변형 중에는 다시 계산하지 않는다(§13.4 규칙 유지). 기각한 대안: 옥타 인코딩(EXT_meshopt OCTAHEDRAL 필터)은 약 2 MB를 아끼지만 인코더 구현이 늘어나고 이득이 작다 |
| `_NODE_ID` | UNSIGNED_INT, 양자화 없음(무손실). meshopt ATTRIBUTES 모드 |
| 인덱스 | UNSIGNED_INT. meshopt **INDICES** 모드(인덱스 시퀀스 코덱 — 구현이 단순하다). TRIANGLES 모드(더 작음)는 후속. 삼각형은 최소 정점 번호 순으로 정렬한다(결정적) |
| 확장 선언 | `extensionsUsed`·`extensionsRequired`에 `KHR_mesh_quantization`·`EXT_meshopt_compression`(meshopt를 끄면 앞의 것만). 대체(fallback) 버퍼는 두지 않는다(뷰어 전용) |
| 결정성 | 같은 입력이면 바이트가 같다 |

### 4.4 인코더 구현과 단계

- `physicsai_core/contour3d/meshopt.py`: 확장 명세(EXT_meshopt_compression)의 vertex codec(v0)과 index sequence codec을 numpy로 구현한다. 외부 의존·네이티브 코드는 없다.
- 검증: Linux 시험이 Python으로 인코딩한 버퍼를 프런트 vitest(Node)에서 three 동봉 `MeshoptDecoder`로 풀어 원본과 바이트가 같은지 확인한다(V-C3F-8).
- 설정 `contour3d.meshopt`(기본 true). 인코더 결함이 생기면 false로 두어 양자화만 쓴다. 키에 들어가 캐시가 분리된다.
- 기각한 대안
  - gltfpack(네이티브 실행 파일): 정점을 다시 배열해서 레코드 대응이 깨진다. 배포할 실행 파일이 하나 늘어난다.
  - `meshopt` wheel(신생 제3자): §17 Q1.

## 5. 필드 압축

### 5.1 파일과 레코드

```text
contour_frames.bin  record(i) = uint16[N]                (LE, 정점 순서)   record_bytes = 2·N
contour_disp.bin    record(i) = uint16[N][3] (dx,dy,dz)   (LE)             record_bytes = 6·N   (선택)
offset(i) = i × record_bytes   (고정 크기 — 프레임 단위 Range 그대로)
```

### 5.2 양자화 규칙과 오차 상한

| 대상 | 부호화 | 복원 | 오차 상한(계약) |
|---|---|---|---|
| 스칼라 | 프레임 i의 NaN 제외 `min_i`·`max_i`. `q = round((v − min_i) / s_i)`, `s_i = (max_i − min_i) / 65534`. NaN·inf → **65535**(예약). `max_i = min_i`면 `s_i = 0`, q = 0 | `v̂ = min_i + q · s_i`(q = 65535 → NaN) | \|v̂ − v\| ≤ s_i / 2 + float32 반올림 = (max_i − min_i) / 131068. 400 MPa 범위면 약 0.003 MPa |
| 변위 | 성분 c별 프레임 범위 `dmin_{i,c}`·`dmax_{i,c}`. `q = round((d − dmin) / t)`, `t = (dmax − dmin) / 65535`. 비유한 → 0 mm로 보고 부호화(현행 규칙) | `d̂ = dmin + q · t` | \|d̂ − d\| ≤ (dmax − dmin) / 131070. 50 mm 범위면 약 0.0004 mm |

- 변위는 "첫 프레임 대비 변화량" 방식을 기각한다. 낙하 충격에서 프레임 사이 변위가 커서 범위가 줄지 않고, 첫 프레임에 의존하게 되어 Range 단독 로드가 깨진다.
- 프레임별 min·max·scale은 원래 float(float64 계산 → JSON 숫자)로 manifest에 둔다. 범례와 극값 표시는 이 정확값을 쓴다.

### 5.3 manifest `schema_version` 2

```json
{"schema_version": 2, "kind": "contour3d", "status": "OK", "converter_version": 2,
 "mesh": {"file": "contour.glb", "sha256": "…", "bytes": 12000000, "nodes": 973060, "triangles": 1950000,
          "compression": "meshopt", "quantization": {"position": "int16n"}, "order": "morton", "normals": "viewer"},
 "lod": {"file": "contour_lod.glb", "sha256": "…", "bytes": 1500000, "vertices": 100000, "triangles": 195000,
         "method": "cluster_peak", "cell_mm": 6.2} ,
 "frames": {"file": "contour_frames.bin", "dtype": "uint16q", "nan_code": 65535, "record_bytes": 1946120, "count": 50,
            "has_disp": true, "nan_count": 0,
            "list": [{"i": 0, "src": 0, "time": 0.0, "min": 0.0, "max": 0.0, "scale": 0.0,
                      "min_v": 0, "max_v": 0}]},
 "disp": {"file": "contour_disp.bin", "dtype": "uint16q", "record_bytes": 5838360, "sha256": "…", "bytes": 291918000,
          "list": [{"i": 0, "min": [0, 0, 0], "scale": [0, 0, 0]}]},
 "range": {"min": 0.0, "max": 412.3}, "unit": "", "unit_source": null,
 "limits": {"nodes": 973060, "max_nodes": 2000000, "glb_bytes": 12000000, "max_glb_bytes": 67108864,
            "bin_bytes": 97306000, "max_bin_bytes": 268435456, "disp_bytes": 291918000, "max_disp_bytes": 1073741824},
 "scope": {"comps": [], "applied": false}, "sampling": {"total_frames": 50, "max_frames": 55, "rule": "uniform_inclusive"},
 "warnings": []}
```

- `frames.list[i].min_v`·`max_v` = 그 프레임 최소·최대 값의 **정점 번호**(GLB 정점 순서, 같으면 작은 번호). 노드 ID는 `_NODE_ID[min_v]`.
- `disp`는 없으면 `null`. `frames.has_disp`는 `disp != null`과 같다.
- `lod`는 N_ext ≤ `lod_min_nodes`이면 `null`.

### 5.4 크기 판정 순서(C3_CONVERT, 결정적)

1. N_ext > `max_nodes` → FAIL `CONTOUR3D_TOO_LARGE`(`limits.nodes`).
2. 형상 GLB(LOD 포함 합)가 `max_glb_bytes`를 넘으면 → FAIL `CONTOUR3D_TOO_LARGE`(`limits.glb_bytes`).
3. 프레임 목록 F를 정한다(TCL 샘플링, `max_frames` 이하).
4. **변위**: 6·N·F > `max_disp_bytes`이면 변위를 뺀다. 경고 `CONTOUR3D_DISP_DROPPED`, 사유 "크기". **프레임은 줄이지 않는다.**
5. **스칼라**: 2·N·F > `max_bin_bytes`이면 floor(`max_bin_bytes`/2N)개로 균등 재샘플한다(첫·끝 포함). 2개보다 적으면 FAIL. 변위가 남아 있으면 같은 프레임 목록을 쓴다.
6. TCL이 노드 수 때문에 변위를 건너뛰었으면(`DISP=SKIPPED_NODES`) 경고 `CONTOUR3D_DISP_DROPPED`, 사유 "노드 수". 변위가 없거나 일부 프레임에만 있으면(`DISP=NONE`·`DISP_MISSING_FRAMES > 0`) `CONTOUR3D_DISP_UNAVAILABLE`(§9.4).

| 경우(새 기본값) | 결과 |
|---|---|
| 97만×50 | 스칼라 97 MB ✓ · 변위 292 MB ✓ → 50프레임 + 변형 |
| 97만×55 | 107 MB · 321 MB ✓ |
| 2M×55 | 스칼라 220 MB ✓ · 변위 660 MB ✓(TCL `disp_max_nodes` 1.5M을 넘으면 변위 추출 생략) |

### 5.5 뷰어 값 표시 규칙

- 색: `q`를 바로 정규화 색 인덱스로 쓴다. 범례 "프레임별"이면 `q / 65534`, "고정"이면 복원값을 `range`로 정규화. q = 65535는 회색.
- **툴팁**(노드 클릭): `노드 {_NODE_ID} · {v̂} {unit}`.
  - v̂는 복원값이다. 소수 자리는 `max(0, −floor(log10(s_i)))`이고 유효숫자는 최대 6자리다. 양자화 간격보다 정밀하게 보이지 않는다.
  - `s_i = 0`이면 `min_i`를 그대로 보인다.
  - 극값 노드(`min_v`·`max_v`)는 manifest의 정확값을 보인다.
- 극값 마커: 현재 프레임 `max_v`(기본) 위치에 화면 크기가 고정된 마커와 라벨 `최대 {max} {unit} · 노드 {id}`를 보인다. [최소도 표시]를 선택할 수 있다. LOD·전체 해상도 모두에서 원 정점 위치(변형 반영)에 보인다.
- 변형: 위치 = 복원 POSITION(float32 mm, 로드할 때 1회 역양자화) + 배율 × d̂.
- `disp = null`(schema 1은 `has_disp=false`)이면 변형 배율 컨트롤을 **숨긴다**(지금은 비활성 — 바꾼다). 비교 모드에서는 두 쪽 모두 변위가 있을 때만 보인다. 경고가 있으면 그 사유 한 줄을 뷰어 아래에 보인다(§12).

### 5.6 artifact·API

- 새 kind는 `CONTOUR3D_DISP`·`CONTOUR3D_LOD`(application/octet-stream·model/gltf-binary, Range 필수)다.
  - 내려받기 상한: `CONTOUR3D_GLB`·`CONTOUR3D_LOD`는 `max_glb_bytes`, `CONTOUR3D_FRAMES`는 `max_bin_bytes`, `CONTOUR3D_DISP`는 `max_disp_bytes`(F5 해소).
  - `db/tables/execution.py`의 kind CHECK 목록과 `geometry.view.MEDIA_KINDS`에 추가한다. 운영 DB CHECK를 바꿔야 하면 Backend가 `0024_*`로 올리고 roadmap에 기록한다(확인 항목).
- `Contour3d` 응답에 `disp_artifact_id`·`lod_artifact_id`(nullable)를 추가한다. 값은 같은 작업의 artifacts에서 kind로 조회한다(캐시 테이블 컬럼은 추가하지 않음). `backend/openapi.json`을 갱신한다.

## 6. 전송 — Range와 HTTP 압축

| 안 | 내용 | 판정 |
|---|---|---|
| (가) **압축 없음 + 고정 크기 레코드** | 양자화로 이미 2~4배 줄였다. GLB는 meshopt로 압축돼 있다. Range 오프셋 = i × record_bytes | **채택** |
| (나) 프레임별 사전 압축(deflate) | 가변 길이 레코드 + manifest 오프셋 표. 브라우저 `DecompressionStream`으로 푼다 | 기각 — uint16 응력장의 추가 이득은 약 1.3~1.8배로 추정되지만 오프셋 표·부분 손상 처리·시험이 늘어난다. 후속 후보 |
| (다) Caddy `encode`(gzip/zstd)를 media에 적용 | 206 응답의 Content-Range가 어느 표현을 가리키는지 모호해진다. 프록시가 Range와 압축을 함께 다루는 동작은 구현마다 다르다 | 금지 |

- 백엔드 media 응답(200·206 모두)에 `Cache-Control: no-transform`을 넣는다.
- `deploy/caddy/physicsai.caddy`에는 지금 `encode`가 없으므로 유지한다. 스니펫 주석에 "대시보드 사이트 전역 `encode`가 있으면 `/physicsai/api/artifacts/*` 경로는 제외하세요"를 추가한다.
- manifest JSON(작음)은 압축 대상이 아니다.

## 7. LOD(단계적 표시)

### 7.1 서버 간략화 방법 비교

| 안 | 의존 | 값 매핑 | 판정 |
|---|---|---|---|
| (가) **대표 원 노드 격자 군집**(numpy, 직접 구현) | 없음(numpy 기존) | LOD 정점 = 원 노드 → 값 그대로 | **채택** — 조작 중에만 보이는 표시용이라 품질 요구가 낮다. 결정적이고 빠르다 |
| (나) meshoptimizer simplify(Python) | PyPI `meshoptimizer`는 알파 sdist만(Windows 오프라인 C++ 빌드 필요). `meshopt` 0.1.1은 간략화 제공 여부가 불확실한 신생 | 정점 부분집합 모드를 쓰면 원 노드 | 기각(의존 리스크) |
| (다) `fast-simplification`(pyvista, MIT 저장소, numpy만, cp312 win wheel) | 새 네이티브 wheel 1개(requirements.lock·collect-offline) | 정점 위치가 바뀌므로 붕괴 대응표로 군 최대값을 매핑 | 대체안(§17 Q1) — 품질은 좋지만 의존이 늘고, 군 대표값이 원 노드 값이 아니다 |
| (라) 브라우저에서 meshoptimizer 간략화(npm `meshoptimizer`, wasm 내장) | 새 npm 의존 | 원 노드 | 기각 — 전체 메시를 받은 뒤에야 계산할 수 있어 첫 표시에 도움이 안 된다 |

### 7.2 군집 규칙(결정적)

1. 키 = (격자 셀 `floor(p / h)`, 정점 법선 주축 방향 6버킷). 법선 버킷이 있으므로 얇은 쿠션의 윗면과 아랫면이 합쳐지지 않는다.
2. 셀 크기 h: 군집 수 ≤ `lod_target_vertices`를 만족하는 가장 작은 h를 bbox 대각선 기준 이분 탐색(최대 20회)으로 정한다.
3. **대표 정점** = 군 안에서 "전체 프레임에 걸친 |값| 최대"가 가장 큰 원 정점이다. 같으면 작은 노드 ID. 평균을 쓰면 피크가 묻히므로 기각한다.
4. LOD 삼각형 = 원 삼각형의 정점을 대표로 바꾼 것. 퇴화·중복은 제거한다.
5. LOD GLB(§4.3과 같은 부호화)는 POSITION, `_NODE_ID`, **`_SRC`**(UNSIGNED_INT, 원 정점 번호)를 담는다. 뷰어는 LOD 값을 전체 레코드에서 `record[_SRC[j]]`로 모은다. LOD 전용 프레임 파일은 없다.
6. 극값 보존: 극값 마커(§5.5)가 원 정점 위치에 늘 보이므로, LOD에서 최대값 위치가 사라지지 않는다. 대표 정점이 피크 우선이라 LOD 색도 보수적이다.

- 현행 1차 범위의 변환은 Python 순수 구현이 원칙이었다(§13.4). 이 계약으로 `contour3d` 변환에 numpy를 허용한다(scipy는 쓰지 않음).

### 7.3 뷰어 전환

| 상태 | 표시 |
|---|---|
| 첫 로드 | `lod`가 있으면 LOD GLB + 첫 프레임 레코드를 먼저 받아 표시(대기 안내 종료). 전체 GLB는 백그라운드로 받는다 |
| 조작 중(OrbitControls start~end, 휠, 재생 중) | LOD |
| 조작 끝 + 250 ms, 재생 정지 | 전체 해상도(받은 경우). 아직 못 받았으면 LOD 유지 + "전체 해상도 받는 중 {p}%" |
| `lod = null` | 늘 전체 |

- 사용자 설정 [항상 전체 해상도]를 둔다(로컬 저장, 기본 끔).
- 두 메시는 같은 색·변형 계산을 공유한다(LOD는 `_SRC`로 모음). 전환할 때 카메라를 유지한다.
- 메모리: 프레임 캐시는 바이트 예산(스칼라 32 MiB, 변위 96 MiB, 각 최소 2프레임)으로 정한다. 변형 배율 기본값은 변위 레코드 ≤ 2 MiB(N ≤ 약 35만)면 1, 넘으면 0이다. 배율 > 0을 고르면 변위 Range를 받기 시작하고 "변형 데이터 프레임당 {x} MB"를 안내한다.

## 8. 상한과 기본값(`contour3d.*`)

| 키 | 현재 | 새 기본 | 근거 |
|---|---|---|---|
| `max_frames` | 50 | **55** | FEM 50프레임(+시작)을 재샘플 없이. 현장 설정과 같음 |
| `max_nodes` | 300,000 | **2,000,000** | 압축은 전송·디스크만 줄이고 GPU 메모리(위치 12 + 색 4 + 법선 12 B/정점 + 인덱스)는 그대로다. 2M ≈ 정점 버퍼 56 MB + 인덱스 48 MB. 조작 중에는 LOD(10만)라 전체 해상도는 정지 화면만 그린다. 현장 97만의 약 2배 여유. 측정(V-C3F-16) 뒤 3M을 검토 |
| `max_glb_bytes` (새) | – | **67,108,864**(64 MiB) | 2M 압축 ≈ 20~30 MB, 양자화만 쓰면 ≈ 64 MB(meshopt를 꺼도 2M을 담음) |
| `max_bin_bytes` | 268,435,456 | **268,435,456**(같은 값, 뜻은 양자화 스칼라 파일) | 2M×55×2 = 220 MB. 현장 yaml의 기존 줄이 그대로 유효하다 |
| `max_disp_bytes` (새) | – | **1,073,741,824**(1 GiB) | 2M×55×6 = 660 MB |
| `disp_max_nodes` (새) | – | **1,500,000** | TCL 변위 추출 시간·임시 CSV(97만×50에서 약 2 GB)를 제한 |
| `lod_min_nodes` (새) | – | **500,000** | 그 이하는 전체만으로 조작이 부드럽다고 추정 |
| `lod_target_vertices` (새) | – | **100,000** | 내장 GPU에서 조작 60 fps 목표 |
| `meshopt` (새) | – | **true** | §4.4 |
| `include_disp`·`timeout_s` | true·1800 | 유지 | 현장 측정 뒤 조정 |
| `geometry.view.cache.max_total_bytes` | 2 GiB | **4 GiB** | 대형 결과 1건 ≈ 0.4 GB |

- 검증: `max_glb_bytes`·`max_disp_bytes` ≥ 1024, `disp_max_nodes` ≥ 0(0 = 변위 늘 뺌), `lod_min_nodes` ≥ 0(0 = 늘 LOD), `lod_target_vertices` 1,000~1,000,000, `max_frames` 2~500.
- 현장 yaml에 예전 `max_nodes: 300000`이 적혀 있으면 그 값을 그대로 쓴다. RELEASES에 "`max_nodes` 줄을 지우거나 2000000으로 바꾸세요"를 적는다.

## 9. TCL·변환기(`contour_extract.tcl`, `contour_capture.tcl`은 바꾸지 않음 — V-GV-16)

### 9.1 설정 키

기존 키 뒤에 **`COMPS`**(Tcl 리스트, 캡처의 `tcl_list` 이스케이프)와 **`DISP_MAX_NODES`**를 추가한다. 키가 없는 예전 설정 파일이면 TCL 기본값을 쓴다(`{}`, 0 = 검사 안 함).

### 9.2 UNIT

- 114행 `catch { hwc result scalar unit } EX_UNIT`를 **지운다**(`EX_UNIT` = `""`). 26.1의 단위 조회 명령은 확인되지 않아 계약하지 않는다. 확인되면 TCL에서만 추가하고, 실패하면 빈 값으로 둔다.
- `parse_result`: 값이 16자를 넘거나, 공백·`"`·`:`를 포함하거나, `invalid`·`error`(대소문자 무시)를 포함하면 `""`로 바꾼다.
- 단위 결정 순서는 TCL 값 → 표시 설정 새 선택 키 `display.unit`(≤ 16자, 캡처 `DISPLAY_KEYS`에 추가, PNG에는 영향 없음) → 빈 값(범례에 단위를 표시하지 않음)이다. manifest에 `unit`·`unit_source`(`"h3d"|"display"|null`)를 쓴다. 표시 설정 편집 화면에 "단위(선택, 예: MPa)" 칸을 추가한다.

### 9.3 단독 실행 안내와 재현

```tcl
set _cfg [file join [file dirname [info script]] extract_settings.tcl]
if {![file exists $_cfg]} {
    puts "contour_extract: extract_settings.tcl not found - run from the platform job folder (_cache/contour3d/<key>/extract)."
    puts "contour_extract: extract_settings.tcl 없음 - 플랫폼 작업 폴더(_cache/contour3d/<키>/extract)에서 실행하세요."
    catch { exit }
    return
}
source $_cfg
```

- 플랫폼 실행에서는 설정 파일이 늘 있으므로 영향이 없다.
- 워커 `c3_convert`: 결과 FAIL이면 `extract/`에서 `*.csv`만 지운다. `extract_settings.tcl`·`extract_result.txt`·`contour_extract.tcl`은 남긴다. OK이면 지금처럼 폴더를 지운다.

### 9.4 변위 판정(노드 상한·변위 없음)과 결과 줄

현장 사실: PhysicsAI 예측 h3d에는 변위 결과가 없을 수 있다. 지금 TCL은 `INCLUDE_DISP=1`(기본값)에서 `ex_query "node.id node.displacement"`가 실패하면 catch가 작업 전체를 `EXTRACT_ERROR`로 끝낸다(203~210행). 수동 실행(`INCLUDE_DISP 0`)은 OK였다. 바꾸는 규칙은 다음과 같다.

1. **노드 상한**: 사용 노드 수를 확정한 뒤 `INCLUDE_DISP`이고 `DISP_MAX_NODES > 0`이며 `EX_NODES > DISP_MAX_NODES`이면 변위를 읽지 않는다. `DISP=SKIPPED_NODES`.
2. **사전 확인(선택, best-effort)**: `catch { hvResult GetDataTypeList $sub } dts`가 성공하고 목록에 이름이 `displacement`(대소문자 무시, 부분 일치)인 항목이 하나도 없으면 변위를 읽지 않는다. `DISP=NONE`, `DISP_REASON=no displacement result type`.
   - 26.1에서 이 명령의 동작은 확인되지 않았다. 오류가 나거나 빈 목록이면 이 단계를 건너뛰고 3으로 판정한다(이 단계는 시간을 아낄 뿐, 결과를 정하지 않는다).
   - 현장 확인 항목(V-C3F-17).
3. **첫 프레임 판정(결정)**: 첫 프레임(`picks` 0번)에서 변위를 한 번 조회한다. 다음 중 하나면 `INCLUDE_DISP`를 0으로 바꾸고 **스칼라만으로 계속**한다. `DISP=NONE`, `DISP_REASON=<오류 문구(정리) 또는 "empty">`.
   - catch 오류
   - 0행
   - 모든 값이 비었거나 3성분이 아님
   - 판정은 frame 파일을 쓰기 전에 하므로 **모든 frame 파일 헤더가 `value` 하나로 일관된다.**
4. **이후 프레임**: 첫 프레임에서 변위가 있었는데 뒤 프레임 조회가 실패하면, 그 프레임의 `dx,dy,dz`를 빈 칸으로 쓰고 계속한다(EXTRACT_ERROR로 끝내지 않는다). 그런 프레임 수를 `DISP_MISSING_FRAMES=<k>`로 기록한다.
5. 스칼라(`contour.value`) 조회 실패는 지금처럼 `EXTRACT_ERROR`다.

`extract_result.txt` 추가 줄(예전 파서는 무시):

| 키 | 값 |
|---|---|
| `DISP` | `ON` \| `OFF`(INCLUDE_DISP 0) \| `SKIPPED_NODES` \| `NONE` |
| `DISP_REASON` | 선택, `NONE`일 때만, 120자 이내 |
| `DISP_MISSING_FRAMES` | `ON`일 때 0 이상 |
| `SCOPE` | `ALL` \| `COMPS` |

변환기·워커:

| 입력 | 처리 |
|---|---|
| `DISP=NONE` | `disp: null`, 경고 **`CONTOUR3D_DISP_UNAVAILABLE`**("결과에 변위가 없어 변형 표시 없이 보입니다", 상세 = `DISP_REASON`). 결과 OK |
| `DISP=ON`이고 `DISP_MISSING_FRAMES > 0` | 일관성을 위해 **변위 전체를 뺀다**. 경고 `CONTOUR3D_DISP_UNAVAILABLE`, 상세 "일부 프레임({k}개)에 변위 없음" |
| `DISP=SKIPPED_NODES`·크기 초과 | `CONTOUR3D_DISP_DROPPED`(§5.4) |
| `DISP=OFF` | 경고 없음 |

- 머리 주석의 `NODES`·`FACES` 설명을 F2의 뜻으로 고친다.

### 9.5 부품 범위(COMPS) — 조립 결과용

- API `_display`는 `cc.resolve_display` 결과의 `comps`(최대 50)도 돌려준다.
  - `PREDICT_H3D`이고 예측 `params.input_kind == "mesh_only"`(쿠션)이면 `[]`.
  - 조립 예측, FEM 검증(쿠션 입력도 재조립 결과), ① run은 표시 설정값을 그대로 쓴다.
- TCL은 캡처 5절을 재사용한다(`hwc hide component all` → `hwc show component "$c"`). **요소 조회만** `hvSel Add "displayed"`로 하고, 노드·프레임 조회는 `all`로 둔다(사용 노드 필터가 범위를 맞춤). `displayed`가 오류이거나 요소가 0건이면 `all`로 다시 조회하고 `SCOPE=ALL`을 쓴다. 26.1 동작은 현장 확인 항목이다.
- 변환기: comps가 있는데 `SCOPE=ALL`이면 경고 `CONTOUR3D_COMPS_IGNORED`("표시 부품 이름을 적용하지 못해 전체를 표시합니다")를 남긴다. FAIL로 만들지 않는다.

### 9.6 변환기 구조(numpy)

| 단계 | 규칙 |
|---|---|
| 형상 | 노드·요소 CSV를 numpy로 읽는다(`np.loadtxt` 대신 csv 스트리밍 → `array` → `np.frombuffer`). 솔리드 면 후보(int32 [M,4])를 행 정렬 → `np.unique(..., return_counts)`로 1회 등장 면만 남긴다. 외부 면 노드 마스크를 만든다. Morton 재배열 순열 `perm`을 만든다 |
| 프레임 | 프레임마다 CSV를 행 단위로 스트리밍해 `keep` 값만 float64 배열에 담는다 → `perm` 적용 → min·max·argmin·argmax → uint16 양자화 → 파일 쓰기. 피크 누적(정점별 프레임 최대 \|값\|)은 LOD 대표 선택에 쓴다 |
| LOD | 프레임 처리 뒤 §7.2(피크 누적 필요) |
| 목표 | 1M 노드·61만 헥사·50프레임에서 피크 ≤ 1.5 GB, 변환 ≤ 10분(현장 측정). 시험은 축소 합성으로 노드당 바이트를 검사한다 |

## 10. 캐시 키·호환·재시도

```text
key = sha256(정규 JSON){source_kind, source_id, h3d_size, h3d_mtime_ns,
  display: {field, dcomp, avgmode, unit}, comps: [정렬·중복 제거, 쿠션이면 []],
  max_frames, include_disp,
  limits: {max_nodes, max_glb_bytes, max_bin_bytes, max_disp_bytes, disp_max_nodes},
  lod: {min_nodes, target_vertices}, meshopt,
  extract_tcl: sha256(유효 추출 TCL)[0:16], converter_version: 2}
```

- `extract_tcl`: API가 `effective_extract_tcl(s)` 파일을 해시한다(약 10 KB, mtime·크기 메모 캐시 허용). TCL을 현장에서 고치면 캐시가 자동으로 새로 만들어진다.
- 상한을 키에 넣는 방식(채택)과 FAIL 행만 상한 스냅숏으로 비교하는 방식을 비교했다. 상한 변경은 드문 관리자 작업이라 규칙 하나인 앞의 방식을 고른다. 뒤의 방식은 적중할 때마다 manifest를 읽어야 한다.
- **호환**: `converter_version` 2라서 v0.2.9 행(OK·FAIL)은 새 키와 일치하지 않는다. 데이터 조작·migration은 없다. 예전 행은 housekeeping으로 정리된다. 남아 있는 동안 `GET /contour3d/{id}`와 뷰어(schema 1 = float32 섞인 레코드)는 그대로 동작한다.

| 상태 | [다시] | 규칙 |
|---|---|---|
| 작업 FAILED(인프라) | 보임 | 캐시하지 않는다. [다시] → 새 작업. 같은 화면에서 자동 재요청은 없다(보일 때 자동 요청은 처음 1회) |
| CANCELED | "다시 만들기" | 지금과 같다 |
| DONE + 결과 FAIL | 숨김 | 사유와 조치를 보인다. 키 요소가 바뀌면 다음 POST가 새 작업을 만든다 |
| EXPIRED·410 | 자동 | 지금과 같다 |

## 11. 설치와 기본값(`deploy/setup_config.py`)

- `resources.contour_extract_tcl`: `repo/resources/hyperview/contour_extract.tcl`이 있고 경로가 안전하면 채운다. **비었거나 키가 없을 때만** 채운다(캡처 TCL 647~651행과 같은 `fill_empty` 규칙).
- `contour3d.enabled`(Q2)

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| (가) **권고** | 새 파일이면 `altair.hw_exe_path`를 찾았을 때 `true`. 기존 파일은 그대로 두고 요약에 "권고: contour3d.enabled=true(hw 감지됨)" 한 줄 | 관리자 값 존중 | 기존 현장은 직접 고쳐야 한다(화면 사유가 안내) |
| (나) | 기존 파일도 `false` + hw가 있으면 `true`로 바꿈 | 자동으로 켜진다 | 일부러 끈 값을 덮어쓴다. 보일 때 자동 요청으로 CPU 대기열 부하가 바로 생긴다 |
| (다) | 코드 기본값 `true`(없으면 `contour3d_missing`이 끔) | 다른 기능과 같은 방식 | yaml에 `false`가 적힌 현장에는 효과가 없다 |

## 12. 대체 표시 사유(프런트, `ContourSlot`·`ContourBody`)

PNG(또는 빈 칸)가 3D 자리에 나오면 칸 맨 위에 `contour-slot-reason` 한 줄(작은 회색, 길면 말줄임 + title 전체)을 보인다.

| 경우 | 문구 |
|---|---|
| 기능 꺼짐(`missing` 첫 키) | `contour3d.enabled` → "3D 꺼짐 — 관리자 설정 contour3d.enabled" · `resources.contour_extract_tcl` → "3D 꺼짐 — 추출 TCL 없음(resources.contour_extract_tcl)" · 템플릿 placeholder → "3D 꺼짐 — HyperView 경로 미설정(<키>)" |
| WebGL 불가 | "3D 불가 — 이 브라우저에서 WebGL2를 쓸 수 없습니다" |
| 원본 없음(`source=null`·409 `PREREQUISITE_MISSING`) | "3D 없음 — 결과 h3d가 없습니다" |
| 409 `CONTOUR3D_NOT_CONFIGURED` | 기능 꺼짐과 같은 문구(응답 `missing`) |
| 403(member, 캐시 없음) | "3D 미생성 — 처음 생성은 power 권한이 필요합니다" |
| 작업 FAILED | "3D 생성 실패 — {message_ko} ({code})" + **[다시]** |
| 결과 FAIL·노드 | "3D 생략 — 외부 면 노드 {N}개 > 상한 {M}. 부품 이름으로 범위를 줄이거나 관리자에게 상한(contour3d.max_nodes) 조정을 요청하세요". 쿠션 입력(comps 없음)이면 "부품 이름으로 범위를 줄이거나 " 부분을 뺀다 |
| 결과 FAIL·형상 | "3D 생략 — 형상 {x} MB > 상한 {y} MB(contour3d.max_glb_bytes), 관리자에게 조정을 요청하세요" |
| 결과 FAIL·프레임 | "3D 생략 — 프레임 2개도 크기 상한(contour3d.max_bin_bytes)을 넘습니다" |
| 결과 FAIL·값 없음 | "3D 생략 — 선택한 결과 값이 없습니다({field})" |

- `limits`는 FAIL manifest(`GET /artifacts/{manifest_artifact_id}/content`)에서 읽는다. 결과 FAIL에도 manifest에 `limits`·상세 `message`를 쓰고, C3_REGISTER는 `nodes = limits.nodes`를 기록한다. 읽지 못하면 `message_ko`만 보인다. 숫자는 천 단위 구분으로 쓴다.
- 경고(`DISP_DROPPED`·`DISP_UNAVAILABLE`·`COMPS_IGNORED`·`FACE_SKIPPED`)는 3D를 보이면서 뷰어 아래 한 줄로 보인다. 예: "변형 표시 없음 — 결과에 변위가 없습니다".

## 13. 잠금 순서 통일(v0.2.9 잔여 위험, [job-queues.md](job-queues.md) §6.1 보강)

- 현재 순서

| 경로 | 순서 |
|---|---|
| `release` | jobs(FOR UPDATE) → worker_slot UPDATE(GPU holder 자신만 해당 행과 일치) |
| `renew` | jobs → slot |
| `reap_expired` | jobs SKIP LOCKED → slot |
| `claim_gpu` 만료 경로 | **slot FOR UPDATE → holder jobs FOR UPDATE** |

- 교착 시나리오: lease가 막 만료된 GPU 작업 J의 `release`와 다른 스레드의 `claim_gpu`가 겹치면 서로를 기다린다(40P01). 지금은 재시도 3회가 받쳐 준다.
- **규칙(C3F-18)**: 기다리는 순서는 **jobs → worker_slot** 하나로 한다. slot을 쥔 트랜잭션은 jobs 행을 `SKIP LOCKED`로만 잠근다.
- `claim_gpu` 수정
  - holder 조회를 `skip_locked`로 바꾼다.
  - 못 얻으면 slot을 비우지 않고 `None`을 돌려준다(다음 폴링 2 s에 다시 시도). holder의 release나 reaper가 곧 slot을 비운다.
  - 수령 결과·GPU 동시 1·순번은 바뀌지 않는다. 스키마 변경도 없다.
- 기각한 안: release에서 slot을 먼저 잠그는 방법. jobs 행을 읽어야 `holds_slot`을 알 수 있고, CPU 작업 해제까지 slot에서 서로 막히게 된다.

## 14. 시험(V-C3F-n) — `scripts/test-all`(Linux·PostgreSQL), 가짜 hw

| ID | 시험 |
|---|---|
| V-C3F-1 | TCL 정적 검사: `result scalar unit` 0건, `source` 전에 `file exists` 검사, 안내 문구 2줄, `COMPS`·`DISP_MAX_NODES`·`DISP=`·`DISP_REASON=`·`DISP_MISSING_FRAMES=`·`SCOPE=` 처리, 변위 조회 catch가 `ex_finish EXTRACT_ERROR`로 이어지지 않음(스칼라 조회 catch와 분리). 캡처 TCL은 바뀌지 않음 |
| V-C3F-2 | `settings_text`: `COMPS`(한글 `\uXXXX`, ASCII)와 `DISP_MAX_NODES`. 쿠션 입력이면 `COMPS {}` |
| V-C3F-3 | `parse_result`: 오류 문구 UNIT → `""`, `MPa` 유지. `DISP`·`DISP_REASON`·`DISP_MISSING_FRAMES`·`SCOPE` 파싱 |
| V-C3F-4 | `cache_key`: §10의 각 요소가 바뀌면 키가 바뀌고, comps 순서·중복은 영향 없음 |
| V-C3F-5 | API: v0.2.9 키의 DONE+FAIL 행이 있을 때 새 설정으로 POST → 202 새 작업. 같은 설정으로 다시 POST하면 적중 |
| V-C3F-6 | 크기 우선순위(축소 상한): 변위 초과 → 변위 제외, 프레임 수 불변 / 스칼라 초과 → 재샘플(변위도 같은 목록) / 2프레임 미만·형상 초과·노드 초과 → FAIL + `limits` |
| V-C3F-7 | 양자화: 합성 필드(NaN·inf·상수 프레임 포함)에서 \|v̂ − v\| ≤ (max−min)/131068(+1e-6 상대), NaN → 65535 → NaN, 상수 프레임 s = 0, 변위 오차 ≤ (dmax−dmin)/131070, `min_v`·`max_v` 정확. 레코드 크기 2N·6N, 바이트 결정성 |
| V-C3F-8 | **meshopt 왕복**: Python 인코딩(ATTRIBUTES: int16 위치·uint32 `_NODE_ID`·`_SRC`, INDICES) → vitest에서 three 동봉 `MeshoptDecoder`로 디코드 → 원본과 바이트 동일. `meshopt: false`이면 확장이 `KHR_mesh_quantization`만. GLTFLoader로 합성 GLB를 읽어 정점 수·`_NODE_ID` 순서 확인 |
| V-C3F-9 | 정점 순서 불변식: Morton 재배열 뒤 `record[i]`가 `_NODE_ID[i]` 노드의 값(합성 값 = 노드 ID 함수로 검증) |
| V-C3F-10 | LOD: 얇은 두 겹 판 합성에서 윗면·아랫면이 합쳐지지 않음(법선 버킷), 정점 ≤ `lod_target_vertices`, 대표 = 군 피크 최대 정점, `_SRC` 범위·결정성, N ≤ `lod_min_nodes`면 `lod: null` |
| V-C3F-11 | 메모리·시간: 합성 두 겹 헥사(노드 10만, 50프레임) `tracemalloc` 피크 노드당 ≤ 1,200 B, 시간을 기록 |
| V-C3F-12 | 전송: media 응답에 `Cache-Control: no-transform`. 새 kind Range 206/416. 상한별 413(GLB가 `ui.max_artifact_bytes` 초과 · `max_glb_bytes` 이하면 200/206). Caddy 스니펫에 `encode` 없음(정적) |
| V-C3F-13 | COMPS·DISP 경고(가짜 hw `SCOPE=ALL`·`DISP=SKIPPED_NODES`). **변위 없음 fixture**: 가짜 hw 새 모드 `no_disp`(`INCLUDE_DISP=1`인데 `DISP=NONE`·`DISP_REASON=…`·헤더 `value`만)로 작업 SUCCEEDED·결과 OK·`disp: null`·경고 `CONTOUR3D_DISP_UNAVAILABLE`. 모드 `disp_partial`(`DISP=ON`·`DISP_MISSING_FRAMES=2`, 해당 프레임 dx·dy·dz 빈 칸)로 변위 전체 제외 + 같은 경고. 워커 FAIL 시 extract에 CSV 0개 + 설정·결과·TCL이 남음 |
| V-C3F-14 | setup_config: `contour_extract_tcl` 빈 값만 채움, `enabled`는 Q2대로 |
| V-C3F-15 | 프런트(jsdom): §12 사유 각 경우(TOO_LARGE에 `973,060`·`2,000,000`, 쿠션이면 부품 문구 없음), [다시]는 FAILED만, 실패 뒤 자동 재요청 0회, schema 1·2 레코드 해석(uint16 복원·NaN 코드), 툴팁 자리수 규칙, LOD↔전체 전환 상태기(조작 시작/끝 + 250 ms, 재생, 전체 미수신), 바이트 예산 LRU, 변위 지연 로드(배율 0이면 disp 요청 0건), `disp: null`·`has_disp=false` manifest에서 변형 배율 컨트롤 미렌더(비교 모드는 한쪽만 없어도 숨김), 극값 마커 값 = manifest 정확값. 빌드본 외부 URL 0건, 허용 모듈 목록(meshopt 디코더 추가) |
| V-C3F-16 | 잠금(PostgreSQL 2연결): `release`가 jobs 행을 잠근 동안 만료 slot의 `claim_gpu` → 기다리지 않고 `None`, 40P01 0건. 커밋 뒤 수령 성공. 정적: holder 잠금 `skip_locked`. V-JQ-17 회귀 |
| V-C3F-17 | **현장(수동, e2e-checklist E9)**: 쿠션 예측(97만, 22프레임)·FEM(50프레임)으로 `limits.nodes`(N_ext 실측), 추출·변환 시간, 변환 피크 메모리, 파일 크기(§3 표 갱신), 사무용 PC의 첫 표시(LOD)·전체 전환·프레임 전환 시간, 조작 fps(LOD·전체), 변형 켬 지연, 극값 마커, 조립 h3d + comps의 26.1 `displayed` 동작, 예측 h3d의 변위 유무와 `hvResult GetDataTypeList` 결과(§9.4 단계 2 확정용) |

## 15. 변경 범위·소유

| 소유 | 파일 | 내용 |
|---|---|---|
| Impl-Backend(TCL) | `resources/hyperview/contour_extract.tcl` | §9.1~9.5(변위 판정 §9.4 포함) |
| Impl-Backend(core) | `contour3d/settings.py` | 키(§10), `CONVERTER_VERSION=2`, settings 키 2개, UNIT 정화, 새 경고 문구 |
| | `contour3d/convert.py`(numpy 재작성, `DISP` 판정 처리)·`glb.py`(양자화·확장)·새 `meshopt.py`·새 `lod.py` | §4·§5·§7·§9.6 |
| | `config/schema_geometry.py`·`validate_geometry.py`·`config/platform.example.yaml` | §8(새 키 6개, cache 4 GiB) |
| | `stage4_predict/contour_capture.py` | `DISPLAY_KEYS`에 `unit` |
| | `db/tables/execution.py`, `geometry/view.py` | kind `CONTOUR3D_DISP`·`CONTOUR3D_LOD`, `MEDIA_KINDS` |
| | `db/repositories/job_lease.py` | §13 |
| Impl-Backend(API) | `services/contour3d_api.py`·`services/contour_capture.py`·`backend/openapi.json` | 키 계산, 쿠션 comps, 응답 `disp_artifact_id`·`lod_artifact_id`, 상한별 내려받기, `no-transform` |
| Impl-Backend(워커) | `worker/…/stage4_predict/contour3d.py` | settings 전달, FAIL 시 extract 보존, 새 artifact 등록, FAIL `nodes` |
| Impl-Backend(배포) | `deploy/setup_config.py`, `deploy/caddy/physicsai.caddy`(주석) | §11·§6 |
| Impl-Backend(시험) | `fake_hw_capture.py`(모드 `no_disp`·`disp_partial` 추가), 시험 | V-C3F-1~14·16. V-C3F-8의 Python 쪽 픽스처(인코딩 버퍼 파일)를 `frontend/src/…/__fixtures__`에 두는 것은 Frontend와 협의(소유 비중첩: Backend가 생성 스크립트, Frontend가 픽스처 커밋) |
| Impl-Frontend | `geomview/contour/*`(ContourSlot·ContourBody·contourCore·ContourViewer·ContourCompare3D·useContour3d), 3D 로더(`setMeshoptDecoder`), 표시 설정 편집(unit), `frontend-dist/` | §4.2·§5.5·§7.3·§12, V-C3F-8(디코드 측)·15, 청크 크기 기록 |
| Plan | 이 문서, geometry-view.md GV-C5, job-queues.md JQ-C2, decisions.md, roadmap.md, e2e-checklist E9 | — |

병합 순서: Backend(core·TCL·API·openapi, 픽스처 생성) → Frontend(생성 타입·디코더·뷰어). 단계를 나눌 수 있다. 1단계 = 상한·키·TCL·사유·잠금·양자화(meshopt false), 2단계 = meshopt·LOD. 1단계만으로도 현장 97만이 표시된다(형상 약 31 MB, 스칼라 1.95 MB/프레임).

## 16. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R1 | meshopt 인코더 자체 구현 결함(디코드 실패·화면 깨짐) | 왕복 바이트 시험(V-C3F-8), `meshopt: false` 즉시 전환(키 분리), 1단계·2단계 분리 |
| R2 | 1M 노드 변환이 CPU 슬롯을 수 분 점유하고 메모리를 쓴다(동시 4) | numpy 구조, 수령 메모리 문, 측정. 넘으면 후속으로 전용 동시 상한 |
| R3 | 격자 군집 LOD의 모양 품질(얇은 부분·구멍) | 조작 중에만 보인다. 법선 버킷. 품질이 문제면 Q1(나)의 fast-simplification으로 전환 |
| R4 | 압축은 GPU 메모리를 줄이지 않는다 — 내장 GPU에서 2M 전체 해상도 정지 화면이 무거울 수 있다 | LOD로 조작 부담을 분리, 현장 측정, 관리자가 상한을 낮춤 |
| R5 | 대시보드 CSP·전역 `encode`가 wasm·Range에 간섭 | §4.2·§6 안내, `no-transform` |
| R6 | 추출 임시 CSV(변위 포함 약 2 GB)·TCL 시간 | `disp_max_nodes`, 변환 뒤 삭제, `timeout_s` 측정 |
| R7 | 26.1 `Add "displayed"`·`GetDataTypeList` 미동작 | `SCOPE=ALL` 폴백 + 경고. 변위 유무는 첫 프레임 조회 판정이 결정(사전 확인은 best-effort) |
| R8 | 현장 yaml의 예전 `max_nodes` 값이 남음 | RELEASES 안내, 사유 문구에 키 이름 |
| R9 | `claim_gpu` SKIP LOCKED로 드문 경합에서 수령이 2 s 늦어짐 | 허용 |
| R10 | 양자화로 툴팁 값이 원값과 미세하게 다름 | 오차 상한 계약, 자리수 규칙, 극값은 정확값 |

## 17. 미결(사용자 결정 질문)

| # | 질문 | 권고 |
|---|---|---|
| Q1 | 서버 간략화·압축에 새 네이티브 Python 의존을 허용할까? (가) 허용 안 함 — numpy 자체 구현(격자 군집 LOD + meshopt 인코더) (나) `fast-simplification` wheel 추가(LOD 품질 ↑, requirements.lock·오프라인 수집에 1개 추가) | **(가)** — 의존·오프라인 리스크가 없다. LOD는 조작 중에만 보인다 |
| Q2 | `contour3d.enabled` 설치 기본: (가) 새 설치만 hw 감지 시 켬, 기존 설정은 권고 줄만 (나) 기존 설정도 hw가 있으면 켬 | **(가)** — 관리자 값 존중. 화면 사유 문구가 안내 |

## 변경 메모

(구현 중 계약과 다르게 해야 하면 여기에 `C3F-Cn`으로 기록하고 Plan 확인을 받는다. 압축 후 실측 크기·청크 크기도 여기에 기록한다.)

- **C3F-C1 (2026-10-23, 구현 차이 — Plan 확인 대상)**: v0.2.10 통합 구현이 계약과 다르게 정한 점이다.
  - migration: `0024_contour3d_field`(down_revision `0023_doe_methods`)가 `ck_artifacts_kind`에 `CONTOUR3D_DISP`·`CONTOUR3D_LOD`를 추가한다(§5.6 확인 항목의 결과 — 제약이 kind를 열거하므로 필요). 테이블·열은 늘지 않는다.
  - meshopt 끔(`contour3d.meshopt: false`): manifest `mesh.compression = "none"`(켬 = `"meshopt"`). GLB는 `EXT_meshopt_compression` 없이 양자화 위치만 쓰며 뷰어는 두 경우를 같은 로더로 읽는다.
  - 전부 NaN 프레임: `frames.list[i]`의 `min`·`max`·`min_v`·`max_v`는 `null`, `scale`은 `0.0`이다. 전 프레임이 그렇다면 `range`도 `null`. 뷰어는 값 없음(NaN)으로 복원하고 극값 마커를 그리지 않으며 프레임별 범례는 전체 범위로 대체한다.
  - `scope.comps_applicable = bool(comps)`(manifest). API `reason.comps_applicable`은 표시 설정의 `comps_applicable`(= 쿠션 입력이 아님)이고, 뷰어는 `reason`이 있으면 그 값, 없으면 manifest `scope`로 "부품 이름으로 범위를 줄이거나" 문구를 정한다.
  - 예전 TCL(`SCOPE=` 줄 없음)에서 comps가 있으면 `COMPS_IGNORED` 경고를 남긴다(`SCOPE=COMPS`가 아니면 적용되지 않은 것으로 본다).
  - GLB 노드: 위치 복원용 `translation`·`scale`은 루트가 아니라 **surface 노드**(노드 1)에 있다. 뷰어는 로드할 때 `matrixWorld`로 한 번 float32 mm로 복원한다.
  - three `GLTFLoader`는 사용자 속성 이름을 소문자로 바꾼다. 파일의 `_NODE_ID`·`_SRC`는 뷰어에서 `_node_id`·`_src`로 읽는다.
  - LOD: 뒤집힌 삼각형(원 메시 법선과 반대 방향)은 5% 미만(시험: 얇은 두 겹 판에서 윗면 법선 +z ≥ 95%, 아랫면 −z ≥ 95%).
  - 표시 설정 `unit`(선택, ≤ 16자)은 캡처 `DISPLAY_KEYS`·응답 `CaptureDisplayOut.unit`에 있고, 템플릿 관리 "컨투어 표시"에 "단위(선택, 예: MPa)" 칸이 있다.
  - V-C3F-8 왕복: `python -m physicsai_core.contour3d.fixture <폴더> [--b64]`가 서버 인코더 출력(meshopt·plain 각 GLB·LOD·프레임·변위·manifest·expected)을 만든다. `frontend/src/__tests__/fixtures/c3f_server`가 `--b64`로 커밋한 픽스처이고(백엔드 시험이 형상 바이트 최신 여부 검사), `contourServerFixture.test.ts`가 위치·노드 ID·값·변위를 합성 입력의 정답과 대조한다. 기존 JS 인코더 픽스처(`c3f_meshopt_plate.glb.b64`)도 유지한다.
  - 극값 마커 좌표(§5.5·§7.2-6 보강): 변환기가 manifest `frames.list[i]`마다 `max_node`·`max_xyz[3]`·`min_node`·`min_xyz[3]`(노드 ID, 첫 프레임 기준 원 좌표 mm — 양자화 전 값)를 넣는다(값 없는 프레임은 null). 극값 정점이 LOD에 없어도 뷰어는 전체 GLB 전에 이 좌표(+변위가 있으면 변위)로 마커·`노드 {id}` 라벨을 그린다. `converter_version`은 2 그대로(필드 추가만) — 필드가 없는 기존 v2 manifest(캐시 재사용)는 예전 방식(메시에서 정점 좌표 조회)으로 폴백한다. 출력은 결정적(시험: 극값 노드가 LOD에 없는 프레임에서도 좌표가 원 노드와 일치).
  - 뷰어 [항상 전체 해상도](§7.3): LOD가 있는 결과에서 보이는 작은 체크(비교 모드에는 없음), localStorage `paiContourAlwaysFull`에 저장(접근 실패는 무시, 기본 끔). 켜면 LOD 메시를 받지 않고 전체를 바로 받으며, 켜는 도중이면 전체를 받은 뒤 조작·재생 중에도 LOD로 내리지 않는다. 끄는데 LOD를 받지 않은 상태면 다시 불러온다. 전체 해상도 받는 중 문구는 `전체 해상도 받는 중 {p}%`(받은 바이트 / manifest `mesh.bytes`, 받는 도중 최대 99, 총량을 모르면 `…`).
