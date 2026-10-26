"""작업 유형과 step 체인(계약 §8.1)."""

from __future__ import annotations

from dataclasses import dataclass


RES_CPU, RES_GPU, RES_NONE = "cpu", "gpu", "none"
RES_KINDS = (RES_CPU, RES_GPU, RES_NONE)


@dataclass(frozen=True)
class StepDef:
    key: str
    kind: str  # LOCAL | INTERNAL | HPC_SUBMIT | HPC_WAIT | COLLECT
    weight: int = 1
    # 자원 종류(job-queues.md JQ-1): LOCAL·HPC_SUBMIT는 cpu|gpu를 반드시 정한다(정적 시험 V-JQ-1). 그 밖(INTERNAL·HPC_WAIT·COLLECT)은
    # none = 중립(INTERNAL은 지금 쥔 슬롯에서 실행, HPC_WAIT·COLLECT는 슬롯 없음). GPU는 PhysicsAI 추론 step만.
    res: str = RES_NONE


@dataclass(frozen=True)
class JobTypeDef:
    job_type: str
    stage: int
    lane: str
    label: str  # 한국어 표시명
    steps: tuple[StepDef, ...]
    stage_label: str = ""  # 예 "①-3" (phase2 §12.9)
    notify_success: bool = True  # False면 시작·성공·차례 알림 생략(phase3 R3-3)

    def needs_slot(self, step: StepDef) -> bool:
        if self.lane == "PREVIEW":  # geometry-view.md §6.2: 전역 슬롯을 잡지 않는 미리보기 레인
            return False
        if step.kind in ("LOCAL", "HPC_SUBMIT"):
            return True
        if step.kind in ("HPC_WAIT", "COLLECT"):
            return False
        return self.lane == "SLOT"

    def step_of(self, step_key: str) -> StepDef:
        for s in self.steps:
            if s.key == step_key:
                return s
        raise KeyError(step_key)

    def weight_of(self, step_key: str) -> int:
        for s in self.steps:
            if s.key == step_key:
                return s.weight
        return 1


JOB_TYPES: dict[str, JobTypeDef] = {
    "DATASET_CREATE": JobTypeDef(
        "DATASET_CREATE",
        3,
        "SLOT",
        "데이터셋 생성",
        (
            StepDef("DS_SCAN", "INTERNAL", 5),
            StepDef("DS_YAML", "INTERNAL", 1),
            StepDef("EDSPY_DATASET_TRAIN", "LOCAL", 60, "cpu"),
            StepDef("EDSPY_DATASET_EVAL", "LOCAL", 33, "cpu"),
            StepDef("DS_REGISTER", "INTERNAL", 1),
        ),
        "③-1",
    ),
    "PACKAGE_EXPORT": JobTypeDef(
        "PACKAGE_EXPORT",
        3,
        "LIGHT",
        "학습 패키지 내보내기",
        (StepDef("PKG_COPY", "INTERNAL", 95), StepDef("PKG_TEXT", "INTERNAL", 5)),
        "③-2",
    ),
    "MODEL_REGISTER": JobTypeDef(
        "MODEL_REGISTER",
        3,
        "LIGHT",
        "모델 등록",
        (
            StepDef("MR_VALIDATE", "INTERNAL", 5),
            StepDef("MR_COPY", "INTERNAL", 60),
            StepDef("MR_PARSE_LOG", "INTERNAL", 30),
            StepDef("MR_REGISTER", "INTERNAL", 5),
        ),
        "③-4",
    ),
    "EVALUATE": JobTypeDef(
        "EVALUATE",
        3,
        "SLOT",
        "평가",
        (StepDef("EV_PREP", "INTERNAL", 5), StepDef("EDSPY_SCORE", "LOCAL", 90, "gpu"), StepDef("EV_PARSE", "INTERNAL", 5)),
        "③-5",
    ),
    "PREDICT": JobTypeDef(
        "PREDICT",
        4,
        "SLOT",
        "예측",
        (
            StepDef("PR_PREP", "INTERNAL", 2),
            StepDef("TPL_RENDER", "INTERNAL", 1),
            StepDef("GEOM_UPDATE", "LOCAL", 20, "cpu"),
            StepDef("MESH", "LOCAL", 15, "cpu"),
            StepDef("RAD_ASSEMBLE", "INTERNAL", 2),
            StepDef("EDSPY_PREDICT", "LOCAL", 40, "gpu"),
            StepDef("CONTOUR_PREVIEW", "LOCAL", 10, "cpu"),
            StepDef("CURVE_PICK", "INTERNAL", 2),
            StepDef("RESPONSE_EXTRACT", "LOCAL", 6, "cpu"),
            StepDef("RESPONSE_TABLE", "INTERNAL", 2),
            StepDef("CONTOUR_CAPTURE", "LOCAL", 8, "cpu"),  # phase3 §15 S10: 실패는 경고(CAPTURE_FAILED)만 — 예측은 성공 유지
        ),
        "④",
    ),
    "PREDICT_VERIFY": JobTypeDef(
        "PREDICT_VERIFY",
        4,
        "SLOT",
        "PBS 검증 해석",
        (
            StepDef("PV_PREP", "INTERNAL", 5),
            StepDef("HPC_SUBMIT", "HPC_SUBMIT", 5, "cpu"),
            StepDef("HPC_WAIT", "HPC_WAIT", 70),
            StepDef("COLLECT", "COLLECT", 10),
            StepDef("PV_EXTRACT", "LOCAL", 8, "cpu"),
            StepDef("PV_TABLE", "INTERNAL", 2),
        ),
        "④",
    ),
    # ---- 3차 조립 FEM 검증(phase3 §21.3.5 S16): 검증 API·종료 훅만 만든다(POST /jobs 불가). HPC 대기는 슬롯 미점유 ----
    "FEM_VERIFY": JobTypeDef(
        "FEM_VERIFY", 4, "SLOT", "조립 FEM 검증",
        (
            StepDef("FV_PREP", "INTERNAL", 3),
            StepDef("FV_MESH", "LOCAL", 5, "cpu"),
            StepDef("FV_ASSEMBLE", "INTERNAL", 2),
            StepDef("HPC_SUBMIT", "HPC_SUBMIT", 5, "cpu"),
            StepDef("HPC_WAIT", "HPC_WAIT", 55),
            StepDef("COLLECT", "COLLECT", 10),
            StepDef("FV_EXTRACT", "LOCAL", 6, "cpu"),
            StepDef("FV_CURVE", "LOCAL", 5, "cpu"),
            StepDef("FV_CAPTURE", "LOCAL", 8, "cpu"),
            StepDef("FV_COMPARE", "INTERNAL", 1),
        ),
        "④", notify_success=False,
    ),
    # ---- ⑤ 해석 등가성 판정(equiv-check.md §4.5): 판정 API·종료 훅만 만든다(POST /jobs 불가). 추출 라이선스(HyperView·T01)라 SLOT ----
    "EQ_CHECK": JobTypeDef(
        "EQ_CHECK", 4, "SLOT", "등가성 판정",
        (StepDef("EQ_PREP", "INTERNAL", 5), StepDef("EQ_EXTRACT", "LOCAL", 60, "cpu"), StepDef("EQ_COMPUTE", "INTERNAL", 30),
         StepDef("EQ_REPORT", "INTERNAL", 5)),
        "⑤", notify_success=False,
    ),
    # ---- 3차 일괄 예측(phase3 §14.5 S9): 입력 생성만 슬롯 점유, run별 하위 PREDICT(prepared)는 BP_ENQUEUE가 대기열에 넣는다 ----
    "PREDICT_BATCH": JobTypeDef(
        "PREDICT_BATCH", 4, "SLOT", "일괄 예측 입력 생성",
        (StepDef("BP_PREP", "INTERNAL", 3), StepDef("BP_GEN", "LOCAL", 90, "cpu"), StepDef("BP_ENQUEUE", "INTERNAL", 2)),
        "④", notify_success=False,
    ),
    # ---- native 형상 엔진 세트 등록(geometry-engine.md §7.3.4): paicad extract·tag 후 세트 등록. 사용자 선택 job_type이 아니라 등록 API가 만든다 ----
    "PARAM_SET_NATIVE": JobTypeDef(
        "PARAM_SET_NATIVE", 4, "SLOT", "형상 준비(Native)",
        (StepDef("NP_PREP", "INTERNAL", 5), StepDef("NP_EXTRACT", "LOCAL", 30, "cpu"), StepDef("NP_TAG", "LOCAL", 55, "cpu"),
         StepDef("NP_VIEW", "LOCAL", 5, "cpu"),  # geometry-view.md §6.3: 공칭 3D 뷰(실패는 경고 VIEW_EXPORT_FAILED, 작업 계속)
         StepDef("BL_MAP", "LOCAL", 5, "cpu"), StepDef("NP_REGISTER", "INTERNAL", 5)),
        "④", notify_success=True,
    ),
    # ---- 형상 미리보기(geometry-view.md §6.4): 전용 레인 PREVIEW(전역 슬롯 미사용, DOE 중에도 실행, 동시 geometry.view.max_concurrent) ----
    "GEOM_PREVIEW": JobTypeDef(
        "GEOM_PREVIEW", 4, "PREVIEW", "형상 미리보기",
        (StepDef("GV_PREP", "INTERNAL", 5), StepDef("GV_RUN", "LOCAL", 90, "cpu"), StepDef("GV_REGISTER", "INTERNAL", 5)),
        "④", notify_success=False,
    ),
    # ---- 조립 매칭(asm-match.md §6.3): 레인 PREVIEW(전역 슬롯 미사용). params.mode가 parts면 AM_PARTS, check면 AM_CHECK만 실행(다른 쪽은 건너뜀).
    # v0.2.9 대기열 분리 계약이 PREVIEW 레인을 바꾸면 그 계약을 따른다(job_types의 lane 한 곳만 바꾸면 됨) ----
    "ASM_MATCH": JobTypeDef(
        "ASM_MATCH", 1, "PREVIEW", "조립 매칭",
        (StepDef("AM_PREP", "INTERNAL", 5), StepDef("AM_PARTS", "LOCAL", 45, "cpu"), StepDef("AM_CHECK", "LOCAL", 45, "cpu"),
         StepDef("AM_REGISTER", "INTERNAL", 5)),
        "①④", notify_success=False,
    ),
    # ---- 결과 3D 컨투어(geometry-view.md §13.5): 열 때 생성(사용자 요청 때만). 2026-10-22 사용자 결정: LIGHT가 아니라 CPU 대기열(구간 레인 SLOT, job-queues.md JQ-8) ----
    "CONTOUR_3D": JobTypeDef(
        "CONTOUR_3D", 4, "SLOT", "결과 3D 컨투어",
        (StepDef("C3_PREP", "INTERNAL", 5), StepDef("C3_EXTRACT", "LOCAL", 70, "cpu"), StepDef("C3_CONVERT", "LOCAL", 20, "cpu"),
         StepDef("C3_REGISTER", "INTERNAL", 5)),
        "④⑤", notify_success=False,
    ),
    # ---- DOE 표본 형상 그리드 미리보기(doe-preview.md §6.1, DP-C6): 레인 PREVIEW가 아니라 CPU 대기열(구간 레인 SLOT, DP_RENDER res=cpu).
    # 단건 미리보기(PREVIEW 레인, 동시 1)를 막지 않는다. 취소 가능·재시도 없음(새로 요청) ----
    "DOE_PREVIEW": JobTypeDef(
        "DOE_PREVIEW", 1, "SLOT", "형상 미리보기(DOE)",
        (StepDef("DP_PREP", "INTERNAL", 5), StepDef("DP_MATRIX", "INTERNAL", 10), StepDef("DP_RENDER", "LOCAL", 80, "cpu"),
         StepDef("DP_REGISTER", "INTERNAL", 5)),
        "①", notify_success=False,
    ),
    # ---- 3차 S17(phase3 §22.3.5): 끝난 배치의 H3D 성능 다시 추출(①-6 TD_RESP_EXTRACT와 같은 HyperView 슬롯) ----
    "PB_RESP_EXTRACT": JobTypeDef(
        "PB_RESP_EXTRACT", 4, "SLOT", "일괄 예측 성능 다시 추출",
        (StepDef("PX_PREP", "INTERNAL", 5), StepDef("RESPONSE_EXTRACT_RUNS", "LOCAL", 90, "cpu"), StepDef("PX_TABLE", "INTERNAL", 5)),
        "④",
    ),
    # ---- 3차 컨투어 재캡처(phase3 §15 S10): 성공한 예측의 h3d로 방향·표시 설정을 바꿔 다시 캡처 ----
    "CONTOUR_RECAPTURE": JobTypeDef(
        "CONTOUR_RECAPTURE", 4, "LIGHT", "컨투어 다시 캡처", (StepDef("CONTOUR_CAPTURE", "LOCAL", 100, "cpu"),),
        "④", notify_success=False,
    ),
    # ---- 2차(phase2 §6.1) ----
    "TD_EXTRACT_PARAMS": JobTypeDef(
        "TD_EXTRACT_PARAMS", 1, "SLOT", "파라미터 추출",
        (StepDef("TX_PREP", "INTERNAL", 5), StepDef("SIMLAB_EXTRACT", "LOCAL", 85, "cpu"), StepDef("TX_PARSE", "INTERNAL", 10),
         StepDef("TX_VIEW", "LOCAL", 5, "cpu")),  # geometry-view.md §6.9: native 공칭 3D 뷰(altair는 SKIPPED, 실패는 경고)
        "①-1",
    ),
    "TD_DOE_GEN": JobTypeDef(
        "TD_DOE_GEN", 1, "SLOT", "DOE·Radioss 입력 생성",
        (StepDef("DG_PREP", "INTERNAL", 5), StepDef("HST_GEN_RADIOSS", "LOCAL", 85, "cpu"), StepDef("DG_SCAN", "INTERNAL", 10)),
        "①-3",
    ),
    "TD_SOLVE": JobTypeDef(
        "TD_SOLVE", 1, "SLOT", "PBS 해석",
        (
            StepDef("TS_PREP", "INTERNAL", 5),
            StepDef("HPC_SUBMIT", "HPC_SUBMIT", 5, "cpu"),
            StepDef("HPC_WAIT", "HPC_WAIT", 70),
            StepDef("COLLECT", "COLLECT", 15),
            StepDef("TS_REGISTER", "INTERNAL", 5),
        ),
        "①-4",
    ),
    "TD_RESULT_IMPORT": JobTypeDef(
        "TD_RESULT_IMPORT", 1, "LIGHT", "결과 가져오기",
        (StepDef("RI_SCAN", "INTERNAL", 5), StepDef("RI_COPY", "INTERNAL", 90), StepDef("RI_REGISTER", "INTERNAL", 5)),
        "①-5",
    ),
    "TD_RESP_EXTRACT": JobTypeDef(
        "TD_RESP_EXTRACT", 1, "SLOT", "run 응답 추출",
        (StepDef("RX_PREP", "INTERNAL", 5), StepDef("RESPONSE_EXTRACT_RUNS", "LOCAL", 90, "cpu"), StepDef("RX_TABLE", "INTERNAL", 5)),
        "①-6",
    ),
    "CU_H3D_PREVIEW": JobTypeDef(
        "CU_H3D_PREVIEW", 2, "SLOT", "h3d 미리보기",
        (StepDef("CP_PREP", "INTERNAL", 5), StepDef("HW_PREVIEW_H3D", "LOCAL", 90, "cpu"), StepDef("CP_PARSE", "INTERNAL", 5)),
        "②-1",
    ),
    "CU_H3D_CURATE": JobTypeDef(
        "CU_H3D_CURATE", 2, "SLOT", "큐레이션",
        (StepDef("HC_PREP", "INTERNAL", 5), StepDef("HVTRANS_CURATE", "LOCAL", 90, "cpu"), StepDef("HC_REGISTER", "INTERNAL", 5)),
        "②-2",
    ),
    "CU_T01_PREVIEW": JobTypeDef(
        "CU_T01_PREVIEW", 2, "SLOT", "T01 미리보기",
        (StepDef("TP_PREP", "INTERNAL", 5), StepDef("HW_PREVIEW_T01", "LOCAL", 90, "cpu"), StepDef("TP_PARSE", "INTERNAL", 5)),
        "②-3",
    ),
    "CU_T01_CURVES": JobTypeDef(
        "CU_T01_CURVES", 2, "SLOT", "곡선 추출",
        (StepDef("TC_PREP", "INTERNAL", 5), StepDef("HW_CURVE_EXPORT", "LOCAL", 90, "cpu"), StepDef("TC_REGISTER", "INTERNAL", 5)),
        "②-4",
    ),
    "SPDM_IMPORT": JobTypeDef(
        "SPDM_IMPORT", 2, "LIGHT", "SPDM 가져오기",
        (StepDef("SI_SCAN", "INTERNAL", 5), StepDef("SI_COPY", "INTERNAL", 90), StepDef("SI_REGISTER", "INTERNAL", 5)),
        "②-0",
    ),
    "OPTIMIZE": JobTypeDef(
        "OPTIMIZE", 5, "SLOT", "최적화",
        (StepDef("OP_PREP", "INTERNAL", 3), StepDef("HST_OPTIMIZE", "LOCAL", 90, "gpu"), StepDef("OP_SUMMARY", "INTERNAL", 7)),
        "⑤",
    ),
    # ---- 3차 플랫폼 내장 최적화 반복(phase3 §18.4 S13): 검증 배치 DONE 종료 훅이 넣는다(POST /jobs로 만들 수 없음) ----
    "SURROGATE_OPT": JobTypeDef(
        "SURROGATE_OPT", 5, "SLOT", "내장 최적화 반복",
        (StepDef("SO_COLLECT", "INTERNAL", 10), StepDef("SO_FIT", "INTERNAL", 45), StepDef("SO_PROPOSE", "INTERNAL", 35),
         StepDef("SO_NEXT", "INTERNAL", 10)),
        "⑤", notify_success=False,
    ),
    # ---- 3차 Study 관리(stage 0, phase3 §5.2) ----
    "STUDY_STORAGE_SCAN": JobTypeDef(
        "STUDY_STORAGE_SCAN", 0, "LIGHT", "용량 계산",
        (StepDef("SS_WALK", "INTERNAL", 90), StepDef("SS_CLASSIFY", "INTERNAL", 10)),
        "관리", notify_success=False,
    ),
    "STUDY_CLEANUP": JobTypeDef(
        "STUDY_CLEANUP", 0, "LIGHT", "Study 정리",
        (StepDef("SC_VALIDATE", "INTERNAL", 5), StepDef("SC_MOVE", "INTERNAL", 90), StepDef("SC_RECORD", "INTERNAL", 5)),
        "관리",
    ),
}

# Study 관리 작업(phase3 R3-2·R3-4): 재시도 불가, 보관 Study에서도 생성 가능
MANAGE_JOB_TYPES = frozenset({"STUDY_STORAGE_SCAN", "STUDY_CLEANUP"})
# 캐시 행이 딸린 작업(geometry-view.md §6.4·§13.5): 재시도 대신 새로 요청(can_retry=false)
NO_RETRY_JOB_TYPES = frozenset({"GEOM_PREVIEW", "CONTOUR_3D", "ASM_MATCH", "DOE_PREVIEW"})

# step 표시명(phase2 §12.9 current_step_label, 한국어)
STEP_LABELS: dict[str, str] = {
    "DS_SCAN": "h3d 수집·분할", "DS_YAML": "데이터셋 사양 작성", "EDSPY_DATASET_TRAIN": "학습 데이터셋 생성",
    "EDSPY_DATASET_EVAL": "평가 데이터셋 생성", "DS_REGISTER": "데이터셋 등록", "PKG_COPY": "패키지 복사",
    "PKG_TEXT": "명령 안내문 작성", "MR_VALIDATE": "모델 폴더 확인", "MR_COPY": "모델 복사", "MR_PARSE_LOG": "학습 로그 해석",
    "MR_REGISTER": "모델 등록", "EV_PREP": "평가 준비", "EDSPY_SCORE": "평가 실행", "EV_PARSE": "점수 해석",
    "PR_PREP": "예측 준비", "TPL_RENDER": "tpl 값 반영", "GEOM_UPDATE": "형상 갱신", "MESH": "메싱",
    "RAD_ASSEMBLE": "입력 조립", "EDSPY_PREDICT": "예측 실행", "CONTOUR_PREVIEW": "컨투어 미리보기",
    "CURVE_PICK": "커브 추출", "RESPONSE_EXTRACT": "응답값 추출", "RESPONSE_TABLE": "응답 표 작성",
    "PV_PREP": "검증 입력 준비", "HPC_SUBMIT": "PBS 제출", "HPC_WAIT": "PBS 대기", "COLLECT": "결과 회수",
    "PV_EXTRACT": "검증 응답 추출", "PV_TABLE": "검증 표 작성",
    "TX_PREP": "CAD 준비", "SIMLAB_EXTRACT": "Altair 파라미터 추출", "TX_PARSE": "파라미터 해석",
    "DG_PREP": "DOE 입력 준비", "HST_GEN_RADIOSS": "입력 생성(run별)", "DG_SCAN": "run 폴더 확인",
    "TS_PREP": "제출 대상 확정", "TS_REGISTER": "회수 결과 등록",
    "RI_SCAN": "결과 폴더 매칭", "RI_COPY": "결과 복사", "RI_REGISTER": "결과 등록",
    "RX_PREP": "응답 추출 준비", "RESPONSE_EXTRACT_RUNS": "run 응답 추출", "RX_TABLE": "응답 표 작성",
    "CP_PREP": "대상 h3d 선택", "HW_PREVIEW_H3D": "h3d 구조 읽기", "CP_PARSE": "미리보기 해석",
    "HC_PREP": "큐레이션 설정 작성", "HVTRANS_CURATE": "hvtrans 큐레이션", "HC_REGISTER": "큐레이션 등록",
    "TP_PREP": "대상 T01 선택", "HW_PREVIEW_T01": "T01 구조 읽기", "TP_PARSE": "미리보기 해석",
    "TC_PREP": "곡선 추출 설정 작성", "HW_CURVE_EXPORT": "곡선 추출", "TC_REGISTER": "곡선 등록",
    "SI_SCAN": "SPDM 파일 확인", "SI_COPY": "SPDM 파일 복사", "SI_REGISTER": "가져오기 등록",
    "OP_PREP": "최적화 입력 준비", "HST_OPTIMIZE": "HyperStudy 최적화", "OP_SUMMARY": "결과 정리",
    "SS_WALK": "파일 확인", "SS_CLASSIFY": "정리 후보 분류",
    "SC_VALIDATE": "정리 대상 확인", "SC_MOVE": "백업 폴더로 이동", "SC_RECORD": "정리 기록",
    "CONTOUR_CAPTURE": "컨투어 캡처",
    "BP_PREP": "일괄 입력 준비", "BP_GEN": "run 입력 생성", "BP_ENQUEUE": "예측 대기열 등록",
    "FV_PREP": "조립 입력 준비", "FV_MESH": "메시 교체(include 변환)", "FV_ASSEMBLE": "조립 입력 만들기",
    "FV_EXTRACT": "응답 추출(예측·FEM)", "FV_CURVE": "커브 비교", "FV_CAPTURE": "컨투어 캡처(예측·FEM)", "FV_COMPARE": "비교 정리",
    "PX_PREP": "다시 추출 대상 확인", "PX_TABLE": "배치 성능 표 갱신",
    "SO_COLLECT": "검증 결과 수집", "SO_FIT": "대리모델 학습", "SO_PROPOSE": "후보 탐색", "SO_NEXT": "검증 배치 등록·마무리",
    "NP_PREP": "준비 파일 모으기", "NP_EXTRACT": "형상 피처 추출", "NP_TAG": "경계 노드 분류",
    "BL_MAP": "baseline 변수 매칭", "NP_REGISTER": "템플릿 등록",
    "NP_VIEW": "3D 보기 만들기", "TX_VIEW": "3D 보기 만들기",
    "GV_PREP": "미리보기 준비", "GV_RUN": "형상 미리보기 실행", "GV_REGISTER": "미리보기 결과 등록",
    "EQ_PREP": "판정 준비(쌍·레시피 확정)", "EQ_EXTRACT": "응답·곡선 추출(없는 값만)", "EQ_COMPUTE": "지표 계산", "EQ_REPORT": "집계·종합 판정",
    "AM_PREP": "조립 매칭 준비", "AM_PARTS": "조립 component 목록", "AM_CHECK": "외곽 노드·CAD 경계 검사", "AM_REGISTER": "매칭 결과 등록",
    "DP_PREP": "미리보기 입력 확인", "DP_MATRIX": "표본 표 계산·셀 선택", "DP_RENDER": "표본 형상 그리기(셀 묶음)", "DP_REGISTER": "미리보기 결과 등록",
    "C3_PREP": "대기·H3D 확인", "C3_EXTRACT": "H3D 읽기(결과 추출)", "C3_CONVERT": "형상·프레임 변환", "C3_REGISTER": "결과 등록",
}

# 미리보기·3D 컨투어는 작업 목록 화면에서 기본 숨김(geometry-view.md §6.4 — 필터 "미리보기 포함")
HIDDEN_BY_DEFAULT = frozenset({"GEOM_PREVIEW", "ASM_MATCH", "DOE_PREVIEW"})

# native 엔진 작업의 화면 step 이름(geometry-engine.md §7.3 — 작업 params의 engine이 native일 때 덮어쓴다)
STEP_LABELS_NATIVE: dict[str, str] = {
    "SIMLAB_EXTRACT": "형상 피처 추출", "HST_GEN_RADIOSS": "형상 모핑 입력 생성", "TPL_RENDER": "샘플 값 작성",
    "GEOM_UPDATE": "CAD 갱신", "MESH": "메시 모핑·검사",
}


# 쿠션 입력 실행의 화면 step 이름(input-kind.md §4.1 — 입력 종류별 덮어쓰기 1곳, 엔진 덮어쓰기보다 우선)
STEP_LABELS_CUSHION: dict[str, str] = {"RAD_ASSEMBLE": "쿠션 입력 복사"}


def step_label(step_key: str | None, engine: str | None = None, input: str | None = None) -> str | None:  # noqa: A002 - 공개 표기 이름
    """화면 step 이름. input = 공개 입력 종류(`assembly|cushion`, input-kind.md) — 생략·assembly는 기존과 같다."""
    if step_key is None:
        return None
    if input == "cushion" and step_key in STEP_LABELS_CUSHION:
        return STEP_LABELS_CUSHION[step_key]
    if engine == "native" and step_key in STEP_LABELS_NATIVE:
        return STEP_LABELS_NATIVE[step_key]
    return STEP_LABELS.get(step_key, step_key)


def stage_label(job_type: str) -> str | None:
    d = JOB_TYPES.get(job_type)
    return d.stage_label or None if d else None


def job_label(job_type: str) -> str:
    d = JOB_TYPES.get(job_type)
    return d.label if d else job_type
