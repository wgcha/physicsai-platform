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
    ),
    "PACKAGE_EXPORT": JobTypeDef(
        "PACKAGE_EXPORT",
        3,
        "LIGHT",
        "학습 패키지 내보내기",
        (StepDef("PKG_COPY", "INTERNAL", 95), StepDef("PKG_TEXT", "INTERNAL", 5)),
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
    ),
    "EVALUATE": JobTypeDef(
        "EVALUATE",
        3,
        "SLOT",
        "평가",
        (StepDef("EV_PREP", "INTERNAL", 5), StepDef("EDSPY_SCORE", "LOCAL", 90), StepDef("EV_PARSE", "INTERNAL", 5)),
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
    ),
}


def job_label(job_type: str) -> str:
    d = JOB_TYPES.get(job_type)
    return d.label if d else job_type
