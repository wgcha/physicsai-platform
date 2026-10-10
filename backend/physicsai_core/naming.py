"""단계 간 공용 이름 규칙(①·④가 함께 쓰는 파라미터·run 이름 정규식, tpl 파일 이름)."""

from __future__ import annotations

import re

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
RUN_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
TPL_NAME = "simlab_parametered_mesh.tpl"
