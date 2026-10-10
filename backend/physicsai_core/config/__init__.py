"""설정 YAML 로드·검증(계약 §14, 예시 config/platform.example.yaml).

- 알 수 없는 키는 오류(pydantic extra=forbid).
- 스키마 검증 실패여도 API는 뜬다: `LoadedConfig.ok=False`, 쓰기 API는 503 CONFIG_INVALID.

schema(스키마) ← rules(공용 규칙) ← validate_stages·validate(검증) ← loader(로드), derived(파생 값).
여기서 기존 공개 이름을 전부 재노출한다(`from physicsai_core.config import ...` 경로 불변).
"""

from __future__ import annotations

from .derived import (  # noqa: F401
    derived_altair_home,
    derived_hstpy_path,
    effective_altair,
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
    DEFAULT_LOG_ERROR_PATTERNS,
    ENV_PROBE_TOOLS,
    LAUNCHER_KEYS,
    RESOURCE_DIR_KEYS,
    RESOURCE_FILE_KEYS,
    AltairCfg,
    AuthCfg,
    CommandsCfg,
    ConfigIssue,
    CurationCfg,
    DatabaseCfg,
    DatasetCfg,
    DatasetOptionsCfg,
    DemoCfg,
    DevPrincipalCfg,
    EnvCheckCfg,
    EnvCheckProbesCfg,
    ErrorBundleCfg,
    HpcAdapterCfg,
    HpcCfg,
    HpcCommandCfg,
    HpcDefaultsCfg,
    HpcTransferCfg,
    LauncherCfg,
    LoadedConfig,
    LoggingCfg,
    MembershipCfg,
    NotificationsCfg,
    OptimizeCfg,
    PackageCfg,
    ParamSetCfg,
    ParserCfg,
    PathMapCfg,
    PredictCfg,
    ResourcesCfg,
    ScoreCfg,
    ServerCfg,
    Settings,
    SpdmImportCfg,
    StorageCfg,
    SummaryParserCfg,
    TrainDataCfg,
    TrainingLogCfg,
    UiCfg,
    WorkerCfg,
)
from .validate import (  # noqa: F401
    validate_settings,
)
