# native 형상 엔진 운영 교체·현장 검증·기본 엔진 전환·롤백 (운영자용)

- 대상: 운영 phase3 서버를 native 형상 엔진(paicad)·형상 뷰·쉘 모핑·내장 최적화(GA/NSGA-II) 브랜치(`feat/r1-ops` 계열)로 **제자리 교체**하고, 운영 환경에서 native를 검증한 뒤 기본 엔진을 바꾸는 서버 관리자·전역 관리자.
- 기준: 2026-10-20 사용자 결정 = **병행 설치 없이 운영 설치를 이 브랜치로 바로 교체**. migration head `0017_geom_view`(운영 phase3 = `0015_doe_platform_gen`). 설치 일반 절차는 [관리자 매뉴얼](admin.md) §2·§3·§10, 계약은 [geometry-engine](../contracts/geometry-engine.md) §5.3.1·§9, [shell-morph](../contracts/shell-morph.md), [geometry-view](../contracts/geometry-view.md) §13, [opt-native](../contracts/opt-native.md).
- 반출 규칙: CAD·메시 원본은 사내 반출 불가. 회신은 **수치만**(§5). `selftest` 출력 폴더의 `work\`에는 작업용 사본이 있으니 보내지 않는다(`selftest_report.json`·`.md`만).

---

## 1. 제자리 교체 (기본 절차)

| 순서 | 동작 | 확인 |
|---|---|---|
| ① | **사전 백업**(모두 `D:\backup\pre_native\` 등 한곳에): 운영 DB `pg_dump -Fc`(admin §3.3, 파일명에 `pre_native`) · 설치 폴더의 `config\platform.yaml`·`deploy\deploy.json` 사본 · `secrets\` 위치만 확인(**값은 기록·복사 금지**, 폴더가 안 지워지는지만 본다) · `frontend-dist` 버전(빌드 해시·`index.html` 날짜) 기록 · 작업 정의 내보내기 `Export-ScheduledTask PhysicsAI-Backend`·`PhysicsAI-Worker`(선택) | 덤프 크기·`pg_restore -l` 열람 가능, `SELECT version_num FROM alembic_version;` = `0015_doe_platform_gen` |
| ② | 사용자·대기열 공지, **대기열 비움**(`-Force` 쓰지 않음). 실행 중 작업은 교체 시 `INTERRUPTED` 된다 | 관리 > 대기열 0건 |
| ③ | **묶음 설치로 업그레이드**: 준비 PC에서 이 브랜치로 묶음을 만들어(admin §2.2·§2.4) 서버에서 `update.ps1`(admin §3.1). git 폴더 설치면 브랜치 전환 후 `update-repo.ps1`(admin §3.0). migration `0016_geometry_engine`·`0017_geom_view`가 올라간다 | 끝 줄 `업데이트 성공` |
| ④ | `platform.yaml`에 native 키 추가(§2) — 운영은 `ai_root`·`server.port`·DB·`altair.*`를 **그대로** 둔다 | `config.valid` 정상 |
| ⑤ | **관리 > 환경 점검**(admin §10) 전체 실행 | `db.migration_head` = `0017_geom_view`, `paicad_version`(paicad·OCP 버전), `storage.ai_root.write`, 실패 0 |
| ⑥ | **기존 phase3 흐름(altair 경로) 회귀 확인**: 기존 파라미터 세트·Study로 ①~⑥ 대표 작업 **각 1회**(① 학습데이터 1건 · ② 정리 · ③ 학습 · ④ 단건 예측 · ⑤ 결과분석 · ⑥ 최적화) | 교체 전과 같이 완료, 화면·알림 정상 |

- ⑥ 중 하나라도 실패하면 새 세트·native 검증으로 넘어가지 않고 원인 확인 또는 §4 롤백을 한다.

## 2. 교체 직후 기본 설정

- **`geometry.engine`은 기본 `altair` 유지**(기존 업무 무중단). native는 **새 파라미터 세트에서 엔진을 선택**할 때만 쓰며, 현장 검증(§3)은 그 세트로 진행한다.
- `altair.hyperstudy_path`·`hstpy_path`: **기존 값을 유지해도 된다**(레거시 경로 그대로 동작). 비워도 ①~⑥은 동작한다(HyperStudy 기능 ①-3 HyperStudy 생성·⑥ 원본 최적화만 꺼지고 `/status` `legacy` 표시, 환경 점검 SKIP. ⑥ 내장 최적화·① 플랫폼 DOE는 키를 보지 않는다).

추가·확인할 `platform.yaml` 키:

| 키 | 값 | 비고 |
|---|---|---|
| `geometry.engine` | `altair` | 기본 유지(native 기본 전환은 §3.2) |
| `geometry.paicad_path` | `""`(venv `Scripts\paicad.exe`) | |
| `commands.paicad_*` | 예시 파일 그대로(extract·tag·update·morph·check·run·version 필수, `props_*`·`map`·`shell_*`·`view_*`·`shell_view_*` 포함) | null이면 그 기능만 비활성 |
| `shell.default_component` | `chassis_rear` | Radioss `/PART` 제목(대소문자 무시). 바디 이름이 다르면 `cad/body_map.json` |
| `geometry.view` | `enabled: true`, `cache: {retention_days: 7, max_total_bytes: 2147483648}` | 미리보기 캐시 = AI 루트 `<study>/_cache/`(서버측 임시 산출물, 자동 삭제 대상) |
| `contour3d` | 처음엔 `enabled: false`. §3.1 (g) 통과 후 `true` + `commands.contour_extract` 확인 | 상한 기본 `max_frames 50`·`max_nodes 300000`·`max_bin_bytes 268435456`·`timeout_s 1800` |

---

## 3. 현장 검증과 기본 엔진 전환

### 3.1 체크리스트 (운영 환경, native 세트로 수행)

공통 준비: 입력 폴더 = 실물 G1(공칭 STEP, baseline `104_*.inc`, `RENUM_INIT.csv`, 조립 폴더 `radioss_assem`, NX 변경 샘플 S1~S3 = 각 `<이름>.step`+`<이름>.json`(values), 쉘은 중립면 STEP). 결과는 `D:\native_accept\<항목>\`에 만든다. `paicad` = `<설치 폴더>\venv\Scripts\paicad.exe`. 검증용 Study·세트는 **새로 만든다**(운영 Study와 섞지 않고, 끝나면 사용자와 합의해 정리 — 삭제하지 않고 `_backup`으로 이동).

합격 기준 중 **(제안)** 표시는 이 문서가 제안하는 값이며 **사용자 확정 대기**다(§6 O3). 확정 전에는 수치를 기입하고 판정은 보류한다.

| # | 항목 | 실행 방법(명령·화면) | 볼 수치 | 합격 기준 | 결과 기입 |
|---|---|---|---|---|---|
| a | paicad selftest(쿠션) | `paicad selftest --cad <공칭.step> --baseline-inc <104_*.inc> --renum-csv <RENUM_INIT.csv> --assem-dir <radioss_assem> --out-dir D:\native_accept\a --envelope-pos-steps 1,3`(필요 시 `--envelope-steps 5,10`). 보고 `selftest_report.json` | `tag.unclassified_total`, `tag.match_ratio`, `roundtrip.writer_byte_identical`·`nominal_morph_byte_identical`, `nominal_check`(status·`quality` stretch·aspect·edge_ratio·dt_ratio·inverted·`baseline_status`·`deviation_max_mm`·`param_max_err_mm`), `envelope.params[*]`(last_ok·first_fail·코드), `elapsed_s` | 미분류 0, `match_ratio` ≥ 0.98, 무변경 바이트 동일 둘 다 true, 공칭 check PASS(반전 0), envelope는 **완료**(숫자 회신이 목적, 첫 실패 직전값 기록) | |
| b | NX 변경 샘플 비교 | (a) 명령에 `--nx-samples D:\native_samples`(샘플 폴더: `S1.step`+`S1.json` …) 추가. 보고 `nx_samples` | 샘플별 `boundary_vs_nx_mm` max·p95, `brep_vs_nx_mm` max, `volume_rel_diff`, `param_remeasure.max_abs_mm`·`max_rel`, update·morph·check 상태 | 경계 편차 max ≤ 0.05 mm(계약 §6.5 `boundary_max_mm`), 파라미터 재측정 ≤ 1%(`param_rel` 0.01, mm 절대 0.05), 부피차 ≤ 0.1%(**제안**), 세 단계 OK | |
| c | 해석 등가성 | 같은 형상·같은 값으로 (1) SimLab 메시 해석 (2) native 모핑 메시 해석을 같은 starter·조건으로 Radioss 실행(① DOE 1점 또는 ④ 단건 예측 입력). 응답은 기존 후처리(컨투어·min/max CSV·곡선)로 추출 | 아래 **응답 표** 각 항목의 두 값·상대차 | **응답 표**의 허용오차(제안) | |
| d | Δt·stretch | Δt: 모핑 메시 해석 `.out`의 초기 Δt(요소 최소)와 baseline 해석 Δt의 비 ↔ `nominal_check.quality.dt_ratio`·`edge_ratio`(샘플은 `check.json`). stretch(Q18): baseline tetra를 SimLab/HyperMesh 품질 검사로 측정한 min stretch ↔ `quality.baseline_min_stretch` | 실제 Δt 비, `dt_ratio`, 두 비의 차; SimLab min stretch, paicad `baseline_min_stretch`, 차; aspect(경계 삼각형)도 있으면 | 실제 Δt 비 ≥ 0.8이고 `dt_ratio` 추정과의 차 ≤ 0.1(**제안**); min stretch 차 ≤ 0.05 절대(**제안**, 식 `2√6·r_in/L_max` 확인). 크게 다르면 식·기준 조정 요청(Q18) | |
| e | native DOE→학습→예측 완주 | ① 학습데이터: 새 Study 생성 → ①-1 CAD·조립 폴더로 파라미터 추출(피처 표·하이라이트 확인, 새 세트에서 엔진 `native` 선택) → ①-3 DOE(`platform`, LHS, `num_runs` 20 정도) → 해석·② 정리 → ③ 데이터셋·학습·평가 → ④ 단건 예측 → ⑤ 결과분석 | 단계별 성공 여부, DOE 스킵 건수·사유 코드(`SKIPPED`), 생성 run 수, 학습 평가 점수(R2·MAE), 예측 입력의 학습 범위 경고 유무, 단계별 소요 | 전 단계 에러 없이 완주. 스킵률 ≤ 20%(**제안**), 스킵은 모두 사유 코드 있음 | |
| f | 쉘 chassis_rear | `paicad shell fixed-scan --assem-dir <radioss_assem> --parts <part_id> --out-dir D:\native_accept\f1 --options <opt.json>` 후 `paicad shell selftest --cad <중립면.step> --assem-dir <radioss_assem> --out-dir D:\native_accept\f2 [--variant-cad <변경형.step> --variant-values <값.json>]` | fixed-scan: `fixed.total`, `by_kind`(INTER_TYPE2·RBE2·RBE3·RBODY·BCS·SHARED), `clusters`; selftest: part 대응률, `tag.match_ratio`, 비드 인식 건수, `moved_fixed_nodes`, baseline 품질(warpage·skew·aspect·Jacobian), 변경형 update 면별 최대 거리 | `fixed.total`이 현장에서 아는 tie·RBE2 연결 노드 수와 일치(차이 사유 설명 가능), `moved_fixed_nodes` = 0, part 대응 100%, `match_ratio` ≥ 0.98, 변경형 면별 거리 ≤ 0.05 mm(**제안**, 솔리드 기준 준용) | |
| g | contour_extract.tcl(hw 26.1) | `contour3d.enabled: true` 후 ⑤ 또는 ④ 결과의 컨투어에서 "3D로 보기"(첫 생성 대기 화면). 실패하면 작업 폴더 `extract_result.txt`·`worker.log` 확인. 한글·공백 경로 h3d도 1건 | `STATUS`(OK/OPEN_ERROR/FIELD_ERROR/EXTRACT_ERROR)와 `MESSAGE`, `NODES`·`FACES`·`FRAMES_TOTAL`, 외부 면을 hw에서 직접 구했나(대체 계산 사용 여부), 총 소요(초), `contour_frames.bin` 크기 | Q4: `STATUS=OK`·프레임 이동·평균 스칼라·변위 읽힘, 소요 ≤ `timeout_s`(1800 s). Q5: `NODES` ≤ `max_nodes`·bin ≤ `max_bin_bytes`로 실물 모델이 들어가는지 — 초과·여유가 크면 **상한 조정 값 회신**(합격이 아니라 조정 자료) | |
| h | 미리보기 시간 | 새 파라미터 세트에서 값을 바꿔 미리보기(`fe=off`) 5회, `fe=check` 2회. DOE 실행 중에도 1회 | 회당 소요(초), 캐시 적중 시 시간, 실패 코드 | `fe=off` 중앙값 ≤ 10 s(**제안**; 계약 목표 "수 초", 타임아웃 60 s), `fe=check` ≤ 타임아웃 300 s, DOE 중 시도가 거부되지 않음(PREVIEW 레인 동시 1) | |
| i | HyperStudy 키 비움·최적화 | `hyperstudy_path`·`hstpy_path`를 **임시로 비우고** 백엔드·워커 재시작 → `/status`(또는 화면)에서 레거시 2개 꺼짐 확인 → ①~⑥ 각 화면 열기·핵심 동작 1회씩. ⑥: `ga`(단일 목적)·`nsga2`(다목적) 각 1회 실행, 검증 `loop`(PREDICT_BATCH → native paicad). 확인 후 레거시를 계속 쓰면 **키를 원래 값으로 되돌리고 재시작** | ①~⑥ 동작 여부, 숨겨진 항목(HyperStudy 생성·원본 최적화), 환경 점검 SKIP 문구, GA·NSGA-II 실행 시간·평가 횟수·최적점 수(다목적은 전선 점 수) | HyperStudy 없이 ①~⑥ 에러 없이 동작, GA·NSGA-II 완료(`ENGINE_MISMATCH` 없음), 검증 루프가 native로 돈다 | |

#### 응답 표 (항목 c — 같은 형상, SimLab 메시 vs 모핑 메시)

| 응답 | 추출 위치 | 허용오차(제안) | 두 값·상대차 기입 |
|---|---|---|---|
| 가속도 피크(지정 센서·방향) | 곡선(필터·단위는 기존 후처리와 동일) | ≤ 5% | |
| 쿠션 최대 변형(변위 최대) | min/max CSV 또는 변위 곡선 | ≤ 5% | |
| 쿠션 최대 응력·변형률(`vonMises` 등) | 컨투어 min/max(동일 범례) | ≤ 10% (요소 크기 의존) | |
| 총 에너지 흡수(쿠션 내부에너지 최종) | 에너지 곡선 | ≤ 5% | |
| 접촉력 피크(쿠션–제품) | 접촉 곡선(있을 때) | ≤ 10% | |
| 시간 이력 일치도(가속도 곡선) | 두 곡선 상관계수 | ≥ 0.95 | |
| 해석 안정성 | `.out` 에너지 오차·질량 증가·Δt | 에너지 오차 ±2%p 이내, 질량 증가 같은 수준 | |

- 허용오차는 메시 차이로 생기는 자연 편차 안에 둔 값이다. 근거를 보강하려면 SimLab 쪽에서 메시 크기를 약간 바꾼 해석 1개를 더 돌려 "SimLab끼리의 차이"를 기준 노이즈로 함께 적는다(선택). 기준이 사용자 확정되면 이 표를 고쳐 쓴다.
- 쉘(chassis_rear)을 모핑한 해석도 같은 표를 적용하되 최대 응력은 비드 주변 요소 크기 영향으로 ≤ 10%(제안).

### 3.2 판정 후 native를 기본 엔진으로 바꾸는 단계

판정 기준 — a·b·d·e·f·i 전부 합격, c는 사용자가 확정한 허용오차 이내, g·h는 합격(또는 사용자가 조건부 수용). 미충족 항목이 있으면 전환하지 않고 `altair` 기본을 유지한 채 §5 양식으로 회신한다.

| 순서 | 동작 | 확인 |
|---|---|---|
| ① | 사용자 공지(새 세트의 기본 엔진이 바뀐다는 것, 기존 altair 세트·Study는 그대로) | |
| ② | 전환 직전 DB `pg_dump`(파일명 `native_state` 표시)·`platform.yaml` 사본 | 덤프 생성 |
| ③ | `platform.yaml` `geometry.engine: native`로 변경, `contour3d`는 (g) 합격 시 `enabled: true`. 백엔드·워커 재시작 | `config.valid` 정상 |
| ④ | 환경 점검 → 기존 altair 세트 Study 열기·단건 예측 1건, 새 세트(기본 native) 준비 1건·미리보기 1건 | altair 세트 동작 불변 |

- 기본 엔진을 바꿔도 이미 만든 세트의 엔진은 바뀌지 않는다(세트에 고정). 문제가 생기면 `geometry.engine: altair`로 되돌리면 새 세트 기본만 원복된다.

---

## 4. 롤백 절차

**원칙**: migration `0016_geometry_engine`은 downgrade가 항상 거부된다(`RuntimeError`). `0017_geom_view`는 미리보기·3D 컨투어 작업·산출물·캐시 행이 하나도 없을 때만 되돌려진다(데이터가 있으면 거부). 따라서 되돌리기 = **백업 DB 복원 + phase3 묶음 재설치 + 백업한 설정 복원**이다(admin §2.8·§3.3).

| 순서 | 동작 | 확인 |
|---|---|---|
| ① | **롤백 직전 현재 DB를 한 번 더 `pg_dump`**(`native_state` 표시) — 재전환용 보관. 이 사이 만든 Study는 복원으로 DB에서 사라진다(폴더는 남음) | 덤프 생성 |
| ② | 작업 2개 중지(`PhysicsAI-Backend`·`PhysicsAI-Worker`), 실행 중 작업은 `INTERRUPTED` 됨 | 작업 상태 Ready 아님 |
| ③ | DB 복원: 같은 DB에 `pg_restore -h 127.0.0.1 -U <운영 앱 역할> -d <운영 DB> --clean --if-exists <pre_native 덤프>`(admin §3.3, 비밀번호는 프로세스 환경변수로) | `SELECT version_num FROM alembic_version;` = `0015_doe_platform_gen` |
| ④ | **phase3 묶음 재설치**: 이전 phase3 묶음(또는 `git checkout <phase3 커밋>` 후 `update-repo.ps1`)의 `update.ps1`(admin §3.1), 또는 `_backup\<UTC>`의 `venv`·`migrations`·프런트를 원위치. `update`가 `alembic upgrade head`를 실행하므로 DB가 ③으로 복원돼 있어야 한다(0017 상태 DB에 phase3 코드가 올라가면 리비전을 몰라 기동 실패) | 끝 줄 `업데이트 성공` |
| ⑤ | **백업한 `platform.yaml`·`deploy.json` 복원**(native 키 `geometry.*`·`shell`·`contour3d`·`paicad_*`는 phase3가 알 수 없는 키로 **설정 오류**가 된다). `secrets\`는 건드리지 않았으므로 그대로 | `config.valid` 정상 |
| ⑥ | 작업 시작 → 환경 점검 → 기존 Study 열기·단건 예측 1건 | `db.migration_head` = `0015_doe_platform_gen` |

AI 루트 산출물:
- native가 만든 `<study>/native/`(준비본)·`04_params/<id>`의 engine=native 세트·`_cache/`는 phase3가 읽지 않으므로 **무시된다**(DB에 행이 없음). native DOE의 run 폴더(`approaches/doe_1/run__*`, phase3 경로와 같은 이름)·`01_train/radioss_assem`은 phase3 폴더 규칙과 같아 DB 복원 후 목록에 없는 학습 폴더로 남는다(읽히지 않음). **native 산출물 폴더는 삭제하지 않는다.** 정리가 필요하면 사용자와 합의하고 `_backup`으로 이동한다.
- 단, `_cache/`(미리보기·컨투어 3D 캐시)는 플랫폼 임시 산출물이라 phase3 쪽에서 쓰지 않으며, 디스크가 부족하면 관리자가 사용자 확인 후 지울 수 있다(사용자 산출물 삭제 금지 규칙과 별개).
- DB와 AI 루트를 같은 시점으로 맞추는 원칙(admin §3.3): 롤백 후 phase3 Study 목록에 없는 폴더가 AI 루트에 남는 것은 정상이다.

확인 항목: ① 기존 phase3 Study 전부 열림 ② altair 세트로 단건 예측 성공 ③ 대기열·알림 정상 ④ `worker.log`에 설정 오류·리비전 오류 없음 ⑤ native 산출물 폴더 삭제 안 됨(`dir` 개수 비교).

---

## 5. 결과 회신 양식(수치만 — CAD·메시·좌표·ID 반출 없음)

보낼 것: `selftest_report.md`(또는 json)와 아래 표. 보내지 않을 것: STEP·inc·rad·h3d, `work\` 폴더, 스크린샷의 노드·요소 ID.

회신 헤더: 날짜 · 서버 · 브랜치·커밋 · `paicad` 버전·OCP 버전(환경 점검 `paicad_version`) · hw 버전(26.1) · 검증자 · 교체 후 altair 회귀(①~⑥) 결과.

| 항목 | 수치 | 판정(O/X/보류) | 비고 |
|---|---|---|---|
| a 미분류 노드 수 / match_ratio | / | | |
| a 무변경 바이트 동일(writer·morph) | / | | |
| a 공칭 check(상태·stretch·aspect·edge_ratio·dt_ratio) | | | |
| a envelope 파라미터별 last_ok·first_fail·코드 | (표) | | |
| a elapsed_s | | | |
| b 경계 편차 max·p95 (mm), 샘플별 | | | |
| b 재측정 오차 max abs(mm)·rel | | | |
| b 부피 상대차 | | | |
| c 가속도 피크 SimLab / 모핑 / 상대차 | / / | | |
| c 최대 변형 | / / | | |
| c 최대 응력·변형률 | / / | | |
| c 총 에너지 흡수 | / / | | |
| c 접촉력 피크 | / / | | |
| c 곡선 상관계수 | | | |
| d 실제 Δt 비 / `dt_ratio` / 차 | / / | | |
| d SimLab min stretch / `baseline_min_stretch` / 차 | / / | | |
| e 완주 단계·스킵 건수(사유 코드)·R2·MAE | | | |
| f `fixed.total`(종류별)·`moved_fixed_nodes`·part 대응률·`match_ratio`·비드 건수 | | | |
| f 쉘 baseline 품질(warpage·skew·aspect·Jacobian) | | | |
| g `STATUS`·NODES·FACES·FRAMES_TOTAL·소요(s)·bin(MiB) | | | |
| g 외부 면 hw 직접 조회 여부, 한글·공백 경로 | | | |
| h 미리보기 `fe=off` 중앙값·최대(s) / `fe=check`(s) | | | |
| i ①~⑥ 동작, GA·NSGA-II 시간·평가 수 | | | |
| 기타 오류 코드(`GEOM_*`·`SHELL_*`·`CONTOUR3D_*`·`VIEW_*`) 건수 | | | |

---

## 6. 미결

| # | 내용 | 담당 |
|---|---|---|
| O3 | §3.1 (c) 응답 허용오차·(b) 부피차·(e) 스킵률·(h) 시간 기준 — **사용자 확정 대기**(제안값 유지) | 사용자 |

(O1 병행 설치 옵션 `task_prefix`·`inherit_existing`은 **해결** — 부록 A. O2 별도 포트 로그인 링크·O4 `/physicsai-native/` 경로 분리는 병행 설치 폐기로 삭제.)

---

## 부록 A (선택). 병행 설치가 꼭 필요할 때

기본은 §1 제자리 교체다. 별도 서버·DB로 먼저 보고 싶을 때만 쓴다.

- 옵션(`deploy.json`, 기본값 = 기존 동작):
  - `task_prefix`(기본 `"PhysicsAI"`): 작업 스케줄러 이름 `<task_prefix>-Backend`·`<task_prefix>-Worker`. 영문자로 시작, 영숫자·`_`·`.`·`-`, 40자 이하. 병행 설치는 설치마다 다른 값(예: `"PhysicsAI-Dev"`).
  - `inherit_existing`(기본 `true`): 이전 설치의 머신 환경변수(`PHYSICSAI_DATABASE_URL`·`PHYSICSAI_CONFIG`)·작업 정의를 이어받는다. 병행 설치는 `false`.
  - `setup.ps1 -TaskPrefix PhysicsAI-Dev -NoInherit`로 주면 deploy.json에 `task_prefix`·`inherit_existing=false`로 저장된다. 해제는 `uninstall-tasks.ps1 -TaskPrefix PhysicsAI-Dev`(또는 이 설치의 deploy.json을 `-ConfigFile`로) — **기본값으로 실행하면 운영 작업(`PhysicsAI-*`)이 해제**된다.
  - `inherit_existing=false`에서 같은 이름의 작업이 다른 설치(실행 파일이 이 런타임 밖)에 등록되어 있으면 setup·install은 아무것도 바꾸기 전에 **중단**하고 "deploy.json의 task_prefix를 이 설치 전용 값으로 바꾸세요"를 안내한다. 이때 `task_prefix`를 바꿔 다시 실행한다.
  - 머신 환경변수 `PHYSICSAI_DATABASE_URL`이 있으면 setup·install이 **경고**한다(값은 출력하지 않음 — 다른 설치의 DB를 가리킬 수 있음). 작업은 `--runtime` 인자로 자기 런타임 파일(`<런타임>\secrets\database_url`)을 우선 쓴다. 지우려면(선택) 관리자 PowerShell에서 `[Environment]::SetEnvironmentVariable('PHYSICSAI_DATABASE_URL', $null, 'Machine')`.
- 분리할 값: `install_root`·`db_name`·`db_role`·`config_path`·`caddy_frontend_root`를 운영과 다르게, `storage.ai_root`를 운영과 다른 폴더(SPDM master·운영 AI 루트와 겹침 금지), `worker.state_dir` 기본 유지(운영 폴더를 가리키면 `physicsai-worker.lock`이 겹침).
- **포트 분리**: 병행 백엔드는 `server.port: 8101`(운영 8100), `host: 127.0.0.1`. 서버 PC 브라우저에서 대시보드 로그인 후 `http://127.0.0.1:8101/physicsai/`로 접속(호스트 이름을 `127.0.0.1`로 통일). 다른 PC용은 Caddy에 별도 포트 사이트(`:8180 { reverse_proxy 127.0.0.1:8101 }`)를 두되 로그인 링크는 어긋날 수 있어 대시보드는 원래 주소로 연다.
