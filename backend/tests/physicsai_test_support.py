"""시험 공용 fixture: 임시 PostgreSQL, 설정, 가짜 대시보드, 가짜 도구, 앱·워커.

PostgreSQL이 없으면 DB 시험은 실패한다(skip 금지, 계약 §18.2).

정의는 `support_*.py`(base·db·tools·app·inputs·resources)에 있고 여기서 전부 재노출한다(R12). 시험의
`from physicsai_test_support import …`와 conftest의 `import *`(fixture·pytest 훅 등록) 경로는 그대로다.
"""

from __future__ import annotations

import os

import pytest

from support_base import (  # noqa: F401 - 재노출(conftest `import *`·시험 import 경로 불변)
    FAKE_TOOLS,
    IS_WINDOWS,
    LIMITER,
    REPO,
)
from support_db import (  # noqa: F401 - 재노출(conftest `import *`·시험 import 경로 불변)
    _find_pg_bin,
    _free_port,
    _TempCluster,
    _with_db,
    db_url,
    engine,
    pg_server,
    run_alembic_upgrade,
)
from support_tools import (  # noqa: F401 - 재노출(conftest `import *`·시험 import 경로 불변)
    _EXE_CACHE,
    _install_fake_tools,
    _windows_tool_exe,
    fake_record,
    fake_tools,
    loaded_config,
    make_settings_dict,
    read_record,
    settings_dict,
)
from support_app import (  # noqa: F401 - 재노출(conftest `import *`·시험 import 경로 불변)
    API,
    app_ctx,
    client,
    fake_dashboard,
    FakeDashboard,
    H,
    PROJECTS,
    USERS,
    wait_for,
    worker_factory,
)
from support_inputs import (  # noqa: F401 - 재노출(conftest `import *`·시험 import 경로 불변)
    make_h3d_tree,
    make_model_folder,
    make_param_set_folder,
    TPL_TEXT,
)
from support_resources import (  # noqa: F401 - 재노출(conftest `import *`·시험 import 경로 불변)
    _p2_env,
    DOE_TYPES,
    LAUNCHER_TEXT,
    LAUNCHERS,
    make_phase2_settings,
    make_resources,
    p2_env,
    pbs_command_cfg,
    PHASE2_COMMANDS,
    SIMLAB_TPL_TEMPLATE,
)


# ---------------------------------------------------------------------------
# 마커(windows·posix)와 "Windows 전용 시험 skip = 실패" 강제(CI windows 잡)
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line("markers", "posix: POSIX 전용 시험(Linux 잡에서 실행). Windows에서는 skip")


def pytest_collection_modifyitems(config, items):
    if not IS_WINDOWS:
        return
    skip = pytest.mark.skip(reason="POSIX 전용 — Linux 잡에서 실행")
    for it in items:
        if it.get_closest_marker("posix") and not any(m.name == "skip" for m in it.iter_markers()):
            it.add_marker(skip)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.skipped and item.get_closest_marker("windows") and os.environ.get("PHYSICSAI_REQUIRE_WINDOWS_TESTS") == "1":
        rep.outcome = "failed"
        rep.longrepr = f"Windows 전용 시험이 skip되었습니다(PHYSICSAI_REQUIRE_WINDOWS_TESTS=1): {rep.longrepr}"


