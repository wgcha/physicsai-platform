"""설정 YAML 로드·검증(계약 §14, 예시 config/platform.example.yaml).

- 알 수 없는 키는 오류(pydantic extra=forbid).
- 스키마 검증 실패여도 API는 뜬다: `LoadedConfig.ok=False`, 쓰기 API는 503 CONFIG_INVALID.

schema(스키마: `_model`·`schema_stages`·`schema_hpc`·`schema_ops`를 Settings로 조립) ← rules(공용 규칙) ← validate_stages·validate(검증) ← loader(로드), derived(파생 값).
여기서 기존 공개 이름을 전부 재노출한다(`from physicsai_core.config import ...` 경로 불변).
"""

from __future__ import annotations

from .derived import (  # noqa: F401
    derived_altair_home,
    derived_hstpy_path,
    derived_paicad_path,
    effective_altair,
    effective_executables,
    redacted_settings,
)
from .loader import (  # noqa: F401
    RESERVED_KEYS,
    absent_keys,
    config_warnings,
    load_config,
    load_config_dict,
)
from .rules import (  # noqa: F401
    PATH_META_CHARS,
    has_unsafe_chars,
    is_abs_path_str,
    paths_overlap,
)
from .schema import (  # noqa: F401
    LAUNCHER_KEYS,
    RESOURCE_DIR_KEYS,
    RESOURCE_FILE_KEYS,
    AltairCfg,
    AuthCfg,
    ConfigIssue,
    DatabaseCfg,
    DevPrincipalCfg,
    LauncherCfg,
    LoadedConfig,
    MembershipCfg,
    ResourcesCfg,
    ServerCfg,
    Settings,
    StorageCfg,
    WorkerCfg,
)
from .schema_geometry import GEOMETRY_ENGINES, GeometryCfg  # noqa: F401
from .schema_hpc import (  # noqa: F401
    CommandsCfg,
    HpcAdapterCfg,
    HpcCfg,
    HpcCommandCfg,
    HpcDefaultsCfg,
    HpcTransferCfg,
    PathMapCfg,
)
from .schema_ops import (  # noqa: F401
    DEFAULT_LOG_ERROR_PATTERNS,
    ENV_PROBE_TOOLS,
    DemoCfg,
    EnvCheckCfg,
    EnvCheckProbesCfg,
    ErrorBundleCfg,
    LoggingCfg,
    NotificationsCfg,
    StudyStorageCfg,
    UiCfg,
)
from .schema_stages import (  # noqa: F401
    CurationCfg,
    DatasetCfg,
    DatasetOptionsCfg,
    OptimizeCfg,
    PackageCfg,
    ParamSetCfg,
    ParserCfg,
    PredictCfg,
    ScoreCfg,
    SpdmImportCfg,
    SummaryParserCfg,
    TrainDataCfg,
    TrainingLogCfg,
)
from .validate import (  # noqa: F401
    validate_settings,
)
