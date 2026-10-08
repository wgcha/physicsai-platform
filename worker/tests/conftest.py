import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "tests"))

from physicsai_test_support import *  # noqa: E402,F401,F403
