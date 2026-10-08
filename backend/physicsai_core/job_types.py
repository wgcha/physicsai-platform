"""작업 유형과 step 체인(계약 §8.1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepDef:
    key: str
    kind: str  # LOCAL | INTERNAL | HPC_SUBMIT | HPC_WAIT | COLLECT
    weight: int = 1


@dataclass(frozen=True)
class JobTypeDef:
    job_type: str
    stage: int
    lane: str
    label: str  # 한국어 표시명
    steps: tuple[StepDef, ...]
    stage_label: str = ""  # 예 "①-3" (phase2 §12.9)

    def needs_slot(self, step: StepDef) -> bool:
        if step.kind in ("LOCAL", "HPC_SUBMIT"):
            return True
        if step.kind in ("HPC_WAIT", "COLLECT"):
            return False
        return self.lane == "SLOT"

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
            StepDef("EDSPY_DATASET_TRAIN", "LOCAL", 60),
            StepDef("EDSPY_DATASET_EVAL", "LOCAL", 33),
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
        (StepDef("EV_PREP", "INTERNAL", 5), StepDef("EDSPY_SCORE", "LOCAL", 90), StepDef("EV_PARSE", "INTERNAL", 5)),
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
            StepDef("GEOM_UPDATE", "LOCAL", 20),
            StepDef("MESH", "LOCAL", 15),
            StepDef("RAD_ASSEMBLE", "INTERNAL", 2),
            StepDef("EDSPY_PREDICT", "LOCAL", 40),
            StepDef("CONTOUR_PREVIEW", "LOCAL", 10),
            StepDef("CURVE_PICK", "INTERNAL", 2),
            StepDef("RESPONSE_EXTRACT", "LOCAL", 6),
            StepDef("RESPONSE_TABLE", "INTERNAL", 2),
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
            StepDef("HPC_SUBMIT", "HPC_SUBMIT", 5),
            StepDef("HPC_WAIT", "HPC_WAIT", 70),
            StepDef("COLLECT", "COLLECT", 10),
            StepDef("PV_EXTRACT", "LOCAL", 8),
            StepDef("PV_TABLE", "INTERNAL", 2),
        ),
        "④",
    ),
    # ---- 2차(phase2 §6.1) ----
    "TD_EXTRACT_PARAMS": JobTypeDef(
        "TD_EXTRACT_PARAMS", 1, "SLOT", "파라미터 추출",
        (StepDef("TX_PREP", "INTERNAL", 5), StepDef("SIMLAB_EXTRACT", "LOCAL", 85), StepDef("TX_PARSE", "INTERNAL", 10)),
        "①-1",
    ),
    "TD_DOE_GEN": JobTypeDef(
        "TD_DOE_GEN", 1, "SLOT", "DOE·Radioss 입력 생성",
        (StepDef("DG_PREP", "INTERNAL", 5), StepDef("HST_GEN_RADIOSS", "LOCAL", 85), StepDef("DG_SCAN", "INTERNAL", 10)),
        "①-3",
    ),
    "TD_SOLVE": JobTypeDef(
        "TD_SOLVE", 1, "SLOT", "PBS 해석",
        (
            StepDef("TS_PREP", "INTERNAL", 5),
            StepDef("HPC_SUBMIT", "HPC_SUBMIT", 5),
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
        (StepDef("RX_PREP", "INTERNAL", 5), StepDef("RESPONSE_EXTRACT_RUNS", "LOCAL", 90), StepDef("RX_TABLE", "INTERNAL", 5)),
        "①-6",
    ),
    "CU_H3D_PREVIEW": JobTypeDef(
        "CU_H3D_PREVIEW", 2, "SLOT", "h3d 미리보기",
        (StepDef("CP_PREP", "INTERNAL", 5), StepDef("HW_PREVIEW_H3D", "LOCAL", 90), StepDef("CP_PARSE", "INTERNAL", 5)),
        "②-1",
    ),
    "CU_H3D_CURATE": JobTypeDef(
        "CU_H3D_CURATE", 2, "SLOT", "큐레이션",
        (StepDef("HC_PREP", "INTERNAL", 5), StepDef("HVTRANS_CURATE", "LOCAL", 90), StepDef("HC_REGISTER", "INTERNAL", 5)),
        "②-2",
    ),
    "CU_T01_PREVIEW": JobTypeDef(
        "CU_T01_PREVIEW", 2, "SLOT", "T01 미리보기",
        (StepDef("TP_PREP", "INTERNAL", 5), StepDef("HW_PREVIEW_T01", "LOCAL", 90), StepDef("TP_PARSE", "INTERNAL", 5)),
        "②-3",
    ),
    "CU_T01_CURVES": JobTypeDef(
        "CU_T01_CURVES", 2, "SLOT", "곡선 추출",
        (StepDef("TC_PREP", "INTERNAL", 5), StepDef("HW_CURVE_EXPORT", "LOCAL", 90), StepDef("TC_REGISTER", "INTERNAL", 5)),
        "②-4",
    ),
    "SPDM_IMPORT": JobTypeDef(
        "SPDM_IMPORT", 2, "LIGHT", "SPDM 가져오기",
        (StepDef("SI_SCAN", "INTERNAL", 5), StepDef("SI_COPY", "INTERNAL", 90), StepDef("SI_REGISTER", "INTERNAL", 5)),
        "②-0",
    ),
    "OPTIMIZE": JobTypeDef(
        "OPTIMIZE", 5, "SLOT", "최적화",
        (StepDef("OP_PREP", "INTERNAL", 3), StepDef("HST_OPTIMIZE", "LOCAL", 90), StepDef("OP_SUMMARY", "INTERNAL", 7)),
        "⑤",
    ),
}

PHASE2_JOB_TYPES = (
    "TD_EXTRACT_PARAMS", "TD_DOE_GEN", "TD_SOLVE", "TD_RESULT_IMPORT", "TD_RESP_EXTRACT", "CU_H3D_PREVIEW",
    "CU_H3D_CURATE", "CU_T01_PREVIEW", "CU_T01_CURVES", "SPDM_IMPORT", "OPTIMIZE",
)

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
    "TX_PREP": "CAD 준비", "SIMLAB_EXTRACT": "SimLab 파라미터 추출", "TX_PARSE": "파라미터 해석",
    "DG_PREP": "DOE 입력 준비", "HST_GEN_RADIOSS": "HyperStudy 입력 생성", "DG_SCAN": "run 폴더 확인",
    "TS_PREP": "제출 대상 확정", "TS_REGISTER": "회수 결과 등록",
    "RI_SCAN": "결과 폴더 매칭", "RI_COPY": "결과 복사", "RI_REGISTER": "결과 등록",
    "RX_PREP": "응답 추출 준비", "RESPONSE_EXTRACT_RUNS": "run 응답 추출", "RX_TABLE": "응답 표 작성",
    "CP_PREP": "대상 h3d 선택", "HW_PREVIEW_H3D": "h3d 구조 읽기", "CP_PARSE": "미리보기 해석",
    "HC_PREP": "큐레이션 설정 작성", "HVTRANS_CURATE": "hvtrans 큐레이션", "HC_REGISTER": "큐레이션 등록",
    "TP_PREP": "대상 T01 선택", "HW_PREVIEW_T01": "T01 구조 읽기", "TP_PARSE": "미리보기 해석",
    "TC_PREP": "곡선 추출 설정 작성", "HW_CURVE_EXPORT": "곡선 추출", "TC_REGISTER": "곡선 등록",
    "SI_SCAN": "SPDM 파일 확인", "SI_COPY": "SPDM 파일 복사", "SI_REGISTER": "가져오기 등록",
    "OP_PREP": "최적화 입력 준비", "HST_OPTIMIZE": "HyperStudy 최적화", "OP_SUMMARY": "결과 정리",
}


def step_label(step_key: str | None) -> str | None:
    if step_key is None:
        return None
    return STEP_LABELS.get(step_key, step_key)


def stage_label(job_type: str) -> str | None:
    d = JOB_TYPES.get(job_type)
    return d.stage_label or None if d else None


def job_label(job_type: str) -> str:
    d = JOB_TYPES.get(job_type)
    return d.label if d else job_type
