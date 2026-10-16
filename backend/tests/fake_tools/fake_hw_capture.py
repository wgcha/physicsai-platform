"""가짜 hw 컨투어 캡처 모드(phase3 §15 S10) — fake_hw가 `-tcl .../contour_capture.tcl`일 때 부른다.

TCL 옆 capture_settings.tcl(Tcl `set NAME 값` 줄)을 읽어 H3D_PATH 존재를 확인하고 OUTDIR에 방향(VIEWS)마다 작은 PNG·동영상
바이트와 capture_result.txt(원본 TCL과 같은 형식)를 쓴다. 모드 FAKE_TOOL_MODE_CAPTURE(다른 hw 모드와 독립):
ok | fail(종료코드 1, 출력 없음) | no_video(동영상 저장 실패) | one_fail(첫 방향 이미지 실패) | open_error(h3d 열기 실패,
STATUS=OPEN_ERROR) | no_manifest(파일만, capture_result.txt 없음) | hang(FAKE_CAPTURE_HANG_S초 대기 후 출력 없이 종료).
FAKE_CAPTURE_VIDEO_BYTES = 동영상 크기(기본 64). 기록은 FAKE_TOOL_RECORD에 {"tool":"hw_capture","mode":"capture","settings":{…}}(다른 hw 기록과 구분).
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
_ESC = {"n": "\n", "t": "\t", "r": "\r"}


def _unquote(body: str) -> str:
    out, i = [], 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt == "u":
            out.append(chr(int(body[i + 2:i + 6], 16)))
            i += 6
        elif nxt == "U":
            out.append(chr(int(body[i + 2:i + 10], 16)))
            i += 10
        else:
            out.append(_ESC.get(nxt, nxt))
            i += 2
    return "".join(out)


_STR = re.compile(r'"((?:[^"\\]|\\.)*)"')


def parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("[list"):
        return [_unquote(m) for m in _STR.findall(raw)]
    m = _STR.fullmatch(raw)
    return _unquote(m.group(1)) if m else raw


def parse_settings(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^set\s+(\w+)\s+(.*)$", line.strip())
        if m:
            out[m.group(1)] = parse_value(m.group(2))
    return out


def main(argv: list[str]) -> int:
    mode = os.environ.get("FAKE_TOOL_MODE_CAPTURE") or "ok"
    tcl = argv[argv.index("-tcl") + 1]
    settings_path = os.path.join(os.path.dirname(os.path.abspath(tcl)), "capture_settings.tcl")
    if not os.path.isfile(tcl) or not os.path.isfile(settings_path):
        print(f"hw (fake) capture: tcl/settings not found: {tcl}", flush=True)
        return 2
    with open(settings_path, encoding="ascii") as fh:  # 플랫폼이 ASCII(\uXXXX)로 쓴다 — 아니면 여기서 실패
        st = parse_settings(fh.read())
    rec = os.environ.get("FAKE_TOOL_RECORD")
    if rec:
        with open(rec, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tool": "hw_capture", "mode": "capture", "argv": argv, "cwd": os.getcwd(), "settings": st},
                                ensure_ascii=False) + "\n")
    if mode == "fail":
        return 1
    if mode == "hang":
        time.sleep(float(os.environ.get("FAKE_CAPTURE_HANG_S") or "60"))
        return 0
    out_dir = st["OUTDIR"]
    rows, status, message = [], "OK", ""
    if mode == "open_error" or not os.path.isfile(st["H3D_PATH"]):
        status, message = "OPEN_ERROR", f"cannot open {st['H3D_PATH']}"
    else:
        n_ok = 0
        for i, view in enumerate(st["VIEWS"]):
            err = []
            img_ok = 0 if (mode == "one_fail" and i == 0) else 1
            if img_ok:
                with open(os.path.join(out_dir, f"{view}.png"), "wb") as fh:
                    fh.write(PNG)
                n_ok += 1
            else:
                err.append("image: fake save failed")
            vid, vname = "-", ""
            if st["SAVE_VIDEO"] == "1":
                vname = f"{view}.{st['VID_EXT']}"
                if mode == "no_video":
                    vid = "0"
                    err.append("video: fake encoder missing")
                else:
                    size = int(os.environ.get("FAKE_CAPTURE_VIDEO_BYTES") or "64")
                    with open(os.path.join(out_dir, vname), "wb") as fh:
                        fh.write((b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * (size // 256 + 1))[:size])
                    vid = "1"
            rows.append([view, str(img_ok), f"{view}.png", vid, vname, "; ".join(err)])
        status = "OK" if n_ok else "SAVE_ERROR"
    if mode != "no_manifest":
        with open(os.path.join(out_dir, "capture_result.txt"), "w", encoding="utf-8") as fh:
            fh.write("# capture_result 1\n")
            fh.write(f"STATUS={status}\n")
            if message:
                fh.write(f"MESSAGE={message}\n")
            for r in rows:
                fh.write("VIEW=" + "|".join(r) + "\n")
    print(f"hw (fake) capture {status} views={len(rows)}", flush=True)
    return 0
