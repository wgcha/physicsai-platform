"""가짜 hw 프레임 조회 모드(data-health.md DH-18) — fake_hw가 `-tcl .../h3d_frame_probe.tcl`일 때 부른다.

TCL 옆 frame_probe_settings.tcl의 `[list idx "h3d" "out"]` 목록을 읽어 out마다 `# h3d_frame_probe 1` 형식 결과를 쓴다.
모드 FAKE_TOOL_MODE_PROBE: ok | fail(종료코드 1, 출력 없음) | open_error(첫 파일 STATUS=OPEN_ERROR) | hang(FAKE_PROBE_HANG_S초 대기).
FAKE_PROBE_FRAMES=프레임 수(기본 5, `파일이름조각=수,…`로 파일별 지정 가능). 기록: FAKE_TOOL_RECORD에 {"tool":"hw_probe","targets":[h3d…]}.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time


def main(argv):
    tcl = argv[argv.index("-tcl") + 1]
    text = open(os.path.join(os.path.dirname(os.path.abspath(tcl)), "frame_probe_settings.tcl"), encoding="utf-8").read()
    targets = re.findall(r'\[list (\d+) "([^"]*)" "([^"]*)"\]', text)
    mode = os.environ.get("FAKE_TOOL_MODE_PROBE", "ok")
    rec = os.environ.get("FAKE_TOOL_RECORD")
    if rec:
        with open(rec, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tool": "hw_probe", "targets": [t[1] for t in targets]}) + "\n")
    if mode == "fail":
        return 1
    if mode == "hang":
        time.sleep(float(os.environ.get("FAKE_PROBE_HANG_S", "30")))
        return 0
    spec = os.environ.get("FAKE_PROBE_FRAMES", "5")
    for n, (idx, h3d, out) in enumerate(targets):
        per = dict(x.split("=") for x in spec.split(",") if "=" in x)
        frames = int(next((v for k, v in per.items() if k in h3d), spec if "=" not in spec else 5))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            if (mode == "open_error" and n == 0) or not os.path.isfile(h3d):
                fh.write("# h3d_frame_probe 1\nSTATUS=OPEN_ERROR\nMESSAGE=cannot open\nFRAMES_TOTAL=0\n")
                continue
            fh.write("# h3d_frame_probe 1\nSTATUS=OK\n" + f"FRAMES_TOTAL={frames}\n")
            for k in range(frames):
                fh.write(f"FRAME={k}|{k}|Time = {k * 0.5:g}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
