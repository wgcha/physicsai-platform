"""설정 스키마 — 단계별 절(③ dataset·package·training_log·score, ④ param_set·predict·predict_batch, ① train_data, ② curation·spdm_import, ⑤ optimize)."""

from __future__ import annotations

from pydantic import Field

from ._model import _M


class DatasetOptionsCfg(_M):
    extract_faces: bool = True
    extract_mdi: bool = False
    extract_time_history_vectors: bool = False


class DatasetCfg(_M):
    holdout_ratio: float = 0.1
    seed: int = 20261008
    split_group: str = "file"
    min_h3d_files: int = 2
    min_psdata_bytes: int = 1048576
    options_default: DatasetOptionsCfg = Field(default_factory=DatasetOptionsCfg)


class PackageCfg(_M):
    link_mode: str = "hardlink_or_copy"


class ParserCfg(_M):
    name: str
    pattern: str


class TrainingLogCfg(_M):
    log_globs: list[str] = Field(default_factory=lambda: ["*.log", "*.txt"])
    max_curve_points: int = 2000
    parsers: list[ParserCfg] = Field(
        default_factory=lambda: [
            ParserCfg(
                name="physicsai_default",
                pattern=r"epoch=\s*(?P<epoch>\d+)\s*/\s*(?P<total>\d+)\s+loss=(?P<loss>[0-9.eE+\-]+)",
            )
        ]
    )


class ScoreCfg(_M):
    write_files: bool = False
    parsers: list[ParserCfg] = Field(default_factory=list)


class ParamSetCfg(_M):
    max_samples: int = 20000
    max_total_bytes: int = 2147483648
    # phase3 §13 S8: 프로젝트 폴더에서 자동 구성 — 탐색 깊이·항목 수·tpl 읽기 크기 상한
    discover_max_depth: int = Field(default=4, ge=0, le=16)
    discover_max_entries: int = Field(default=5000, ge=1, le=200000)
    discover_tpl_max_bytes: int = Field(default=1048576, ge=1024)
    # phase3 §14.4 S9: tpl의 SimLab 내보내기 줄(원본 tpl:110 `dir_file_export`) — 값 ≠ predict.simlab_mesh_name이면 등록 경고
    tpl_export_regex: str = r'dir_file_export\s*=\s*r?"[^"]*"'


class PredictCfg(_M):
    """④ 예측(phase3 §11.4·§11.5·§11.8). 파일 이름 기본값은 원본 인용(tpl `dir_file_export`, HyperMesh m_2)."""

    rendered_script_name: str = "simlab_parametered_mesh.py"
    simlab_mesh_name: str = "EPS_mesh_0000.rad"
    mesh_include_name: str = "104_replace_node_elem.inc"
    renum_csv_name: str = "RENUM_INIT.csv"
    mesh_log_complete_marker: str = "COMPLETE HM BATCHRUN"
    mesh_output_glob: str | None = None  # 폐지(phase3 §11.4) — 기존 설정 호환용으로만 받고 값은 쓰지 않는다(config.warnings)
    starter_glob: str = "*_0000.rad"
    integer_rounding: str = "half_up"
    env: dict[str, str] = Field(default_factory=lambda: {"EDS_TNS_ACTVN_CHCKPT": "1"})
    prepared_input_exts: list[str] = Field(default_factory=lambda: [".rad", ".hm"])
    prepared_max_files: int = 500
    prepared_max_total_bytes: int = 2147483648


class PredictBatchCfg(_M):
    """④ 일괄 예측(DOE)(phase3 §14.5·§14.7 설정). 동시 실행 상한은 train_data.max_multi_execution을 쓴다."""

    max_runs: int = 200  # 조합(run) 수 상한 — LHS count 2~max_runs, 표 행 1~max_runs
    table_max_bytes: int = 1048576  # 표 붙여넣기·CSV 텍스트 상한(UTF-8 바이트)
    dir_name: str = "04_batch"  # Study 직계 배치 폴더(<study>/04_batch/B-003)
    curve_max_runs: int = 200  # 커브 겹쳐보기 run 상한(doe_no 앞쪽부터)


class TrainDataCfg(_M):
    """① 학습데이터 생성(phase2 §8.2). 기본값은 원본 인용."""

    cad_extensions: list[str] = Field(default_factory=lambda: [".prt"])
    max_xml_bytes: int = 4194304
    extract_progress_token: str = "Passed"
    extract_progress_total: int = 4
    param_default_range_ratio: float = 0.05
    param_default_format: str = "%3i"
    tpl_marker: str = "#" + "*" * 63
    tpl_prt_regex: str = r'dir_file_prt\s*=\s*r"[^"]*"'
    tpl_parameter_line_regex: str = r"(?m)^[^\n]*\{parameter\(.*?\)\}[^\n]*\n?"
    tpl_paramitem_line_regex: str = r"(?m)^[^\n]*<paramitem[^>]*/>[^\n]*\n?"
    max_runs: int = 2000
    recommended_doe_type: str = "TYPE_LATINHYPERCUBE"  # ① 추천 DOE 유형 value(S15, D3-63). 빈 문자열·정의 파일에 없는 값 = 추천 없음
    max_multi_execution: int = 8
    hst_progress_regex: str = r"Finished run\s*\(\s*(?P<run>\d+)\s*\),\s*model\s*\(\s*m_?3\s*\)"
    hst_log_error_patterns: list[str] = Field(default_factory=lambda: [
        r"^\s*\d+\s+Error\s*:",
        r"Traceback \(most recent call last\):",
        r"^\s*\[ERROR\]",
        r"^\s*(?:FileNotFoundError|RuntimeError|ValueError|OSError|PermissionError|ImportError|TypeError|AttributeError|NameError|SyntaxError)\s*:",
    ])
    run_dir_glob: str = "approaches/*/run__*"
    samples_extractor: str = "paramitem"
    rendered_tpl_glob: str = "**/*"
    rendered_tpl_exts: list[str] = Field(default_factory=lambda: [".py", ".tcl", ".txt", ".xml", ""])
    samples_scan_max_bytes: int = 1048576
    paramitem_regex: str = r'<paramitem\s+Name="(?P<name>[^"]+)"\s+NewValue="(?P<value>[^"]*)"'
    samples_csv_glob: str | None = None
    samples_csv_run_column: str = "run_key"
    max_runs_per_submit: int = 500
    result_run_dir_regex: str = r"^(?P<run_key>run__\d+)$"
    result_match_depth: int = 3


class CurationCfg(_M):
    max_files: int = 20000


class SpdmImportCfg(_M):
    patterns: list[str] = Field(default_factory=lambda: ["*.h3d", "*T01"])
    max_files: int = 20000
    max_total_bytes: int = 536870912000


class SummaryParserCfg(_M):
    name: str
    glob: str
    kind: str
    max_rows: int | None = None


class SurrogateOptCfg(_M):
    """⑤ 플랫폼 내장 최적화(phase3 §18.9 S13). 기본값은 이 한 곳(deploy/setup_config.py는 키를 쓰지 않는다)."""

    enabled: bool = True
    dir_name: str = "05_opt/surrogate"  # Study 기준 <study>/05_opt/surrogate/SO-001
    max_variables: int = 20
    max_iterations: int = 10
    max_candidates: int = 10
    default_iterations: int = 3
    default_candidates: int = 4
    default_tol_rel: float = 0.01
    default_surrogate: str = "gp"  # gp | rbf
    gp_restarts: int = 8
    de_maxiter: int = 200
    de_popsize: int = 15
    fit_timeout_s: int = 600
    blas_threads: int = 4  # 워커 안 numpy BLAS 스레드 상한(worker.max_logical_cores와 작은 쪽, 공유 워커 보호)
    # S17 다목적(phase3 §22.11)
    max_objectives: int = 3
    max_observe: int = 10
    max_extra_points: int = 10
    mo_lattice_h2: int = 10  # 2목적 Das–Dennis 격자 H(→ 11점)
    mo_lattice_h3: int = 6  # 3목적 격자 H(→ 28점)
    mo_de_maxiter: int = 100
    mo_rho: float = 0.05  # 증강 Chebyshev ρ
    mo_ref_offset: float = 0.1  # HV 기준점 = (1 + offset)·1
    mo_gp_restarts: int = 4  # ParEGO 스칼라화 GP 재시작
    mo_hvi_share_m3: float = 0.5  # 3목적 HVI 활용 후보 비율(⌈k·share⌉, 0 = 1개 — 계약 §22.5.4 원안)
    mo_front_prox_m3: float = 6.0  # 3목적 ParEGO 획득값 × exp(−prox·예측 전선까지 정규화 거리)(0 = 끔)


class OptimizeCfg(_M):
    default_study_folder: str = "HST_PHYSICSAI_OPTIMIZATION"
    env: dict[str, str] = Field(default_factory=lambda: {"EDS_TNS_ACTVN_CHCKPT": "1"})
    progress_regex: str = r"Started\s+run\s+\(\s*(?P<run>\d+)\s*\),\s*model\s+\(\s*m_1\s*\)"
    max_listed_files: int = 5000
    viewable_globs: list[str] = Field(default_factory=lambda: ["*.csv", "*.txt", "*.json", "*.log"])
    max_viewable_files: int = 200
    summary_parsers: list[SummaryParserCfg] = Field(default_factory=list)
