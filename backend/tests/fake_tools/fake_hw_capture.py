"""가짜 hw 컨투어 캡처 모드(phase3 §15 S10) — fake_hw가 `-tcl .../contour_capture.tcl`일 때 부른다.

TCL 옆 capture_settings.tcl(Tcl `set NAME 값` 줄)을 읽어 H3D_PATH 존재를 확인하고 OUTDIR에 방향(VIEWS)마다 작은 PNG·동영상
바이트와 capture_result.txt(원본 TCL과 같은 형식)를 쓴다. 모드 FAKE_TOOL_MODE_CAPTURE(다른 hw 모드와 독립):
ok | fail(종료코드 1, 출력 없음) | no_video(동영상 저장 실패) | one_fail(첫 방향 이미지 실패) | open_error(h3d 열기 실패,
STATUS=OPEN_ERROR) | no_manifest(파일만, capture_result.txt 없음) | hang(FAKE_CAPTURE_HANG_S초 대기 후 출력 없이 종료) |
no_file(S16: 동영상 성공 보고(video=1)인데 파일 없음) | zero_video(S16: 성공 보고 + 0바이트 파일).
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
                elif mode == "no_file":
                    vid = "1"
                elif mode == "zero_video":
                    open(os.path.join(out_dir, vname), "wb").close()
                    vid = "1"
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


def main_extract(argv: list[str]) -> int:
    """결과 3D 컨투어 추출 모드(geometry-view.md §13.5 시험) — fake_hw가 `-tcl .../contour_extract.tcl`일 때 부른다.

    TCL 옆 extract_settings.tcl(H3D_PATH OUTDIR FIELD DCOMP AVGMODE MAX_FRAMES INCLUDE_DISP)을 읽어 합성 nodes·faces·frame_*.csv와
    extract_result.txt를 쓴다. 모드 FAKE_TOOL_MODE_CONTOUR3D: ok(쿼드 쉘 2개, faces.csv) | elements(육면체 1 + 쿼드 쉘 1 → elements.csv,
    플랫폼이 외부 면 계산) | open_error | field_error | invalid(프레임 행 수 불일치) | nan(값 전부 빈 칸 → FIELD_EMPTY) |
    hang(FAKE_CAPTURE_HANG_S초 대기) | fail(종료코드 1, 출력 없음) |
    no_disp(C3F-19: INCLUDE_DISP=1인데 변위 없음 → `DISP=NONE`·`DISP_REASON`, frame 헤더 `value`만) |
    disp_partial(C3F-19: `DISP=ON`·`DISP_MISSING_FRAMES=2`, 끝 2프레임의 dx·dy·dz 빈 칸) | skipped_nodes(`DISP=SKIPPED_NODES`, 헤더 `value`) |
    scope_all(COMPS가 있어도 적용 못 함 → `SCOPE=ALL`). 그 밖의 모드는 COMPS가 있으면 `SCOPE=COMPS`, 없으면 `SCOPE=ALL`.
    FAKE_CONTOUR3D_FRAMES = h3d 전체 프레임 수(기본 5). FAKE_CONTOUR3D_UNIT = UNIT 값(기본 MPa — 예전 TCL의 오류 문구 시험용)."""
    mode = os.environ.get("FAKE_TOOL_MODE_CONTOUR3D") or "ok"
    tcl = argv[argv.index("-tcl") + 1]
    sp = os.path.join(os.path.dirname(os.path.abspath(tcl)), "extract_settings.tcl")
    if not os.path.isfile(tcl) or not os.path.isfile(sp):
        print(f"hw (fake) contour3d: tcl/settings not found: {tcl}", flush=True)
        return 2
    with open(sp, encoding="ascii") as fh:
        st = parse_settings(fh.read())
    rec = os.environ.get("FAKE_TOOL_RECORD")
    if rec:
        with open(rec, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tool": "hw_contour3d", "argv": argv, "cwd": os.getcwd(), "settings": st}, ensure_ascii=False) + "\n")
    if mode == "fail":
        return 1
    if mode == "hang":
        time.sleep(float(os.environ.get("FAKE_CAPTURE_HANG_S") or "60"))
        return 0
    out = st["OUTDIR"]

    comps = st.get("COMPS") or []
    disp_in = st["INCLUDE_DISP"] == "1"
    disp_state = "ON" if disp_in else "OFF"
    disp_reason, missing = "", 0
    if disp_in and mode == "no_disp":
        disp_state, disp_reason = "NONE", "no displacement result type"
    elif disp_in and mode == "skipped_nodes":
        disp_state = "SKIPPED_NODES"
    elif disp_in and mode == "disp_partial":
        missing = 2

    def result(status, msg="", nodes=0, faces=0, total=0, frames=()):
        with open(os.path.join(out, "extract_result.txt"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# contour_extract 1\n")
            fh.write(f"STATUS={status}\n")
            if msg:
                fh.write(f"MESSAGE={msg}\n")
            fh.write(f"UNIT={os.environ.get('FAKE_CONTOUR3D_UNIT', 'MPa')}\nFIELD={st['FIELD']}\nDCOMP={st['DCOMP']}\nAVGMODE={st['AVGMODE']}\n")
            fh.write(f"NODES={nodes}\nFACES={faces}\nFRAMES_TOTAL={total}\n")
            fh.write(f"DISP={disp_state}\n")
            if disp_state == "NONE":
                fh.write(f"DISP_REASON={disp_reason}\n")
            if disp_state == "ON":
                fh.write(f"DISP_MISSING_FRAMES={missing}\n")
            fh.write(f"SCOPE={'COMPS' if comps and mode != 'scope_all' else 'ALL'}\n")
            for f in frames:
                fh.write("FRAME=" + "|".join(str(x) for x in f) + "\n")

    if mode == "open_error" or not os.path.isfile(st["H3D_PATH"]):
        result("OPEN_ERROR", f"cannot open {st['H3D_PATH']}")
        return 0
    if mode == "field_error":
        result("FIELD_ERROR", "no such result type")
        return 0
    if mode == "elements":
        coords = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1), (2, 0, 0), (2, 1, 0)]
        with open(os.path.join(out, "elements.csv"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("elem_id,config,n1,n2,n3,n4,n5,n6,n7,n8\n")
            fh.write("1,208,101,102,103,104,105,106,107,108\n")
            fh.write("2,104,102,109,110,103,,,,\n")
    else:
        coords = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)]
        with open(os.path.join(out, "faces.csv"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("elem_id,n1,n2,n3,n4\n1,101,102,105,104\n2,102,103,106,105\n")
    ids = [101 + i for i in range(len(coords))]
    with open(os.path.join(out, "nodes.csv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("node_id,x,y,z\n")
        for nid, c in zip(ids, coords):
            fh.write(f"{nid},{c[0]},{c[1]},{c[2]}\n")
    total = int(os.environ.get("FAKE_CONTOUR3D_FRAMES") or "5")
    mf = int(st["MAX_FRAMES"])
    picks = list(range(total)) if total <= mf else sorted({int(round(k * (total - 1) / (mf - 1))) for k in range(mf)})
    disp = disp_in and disp_state == "ON"
    frames = []
    for oi, src in enumerate(picks):
        with open(os.path.join(out, f"frame_{oi:05d}.csv"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("value,dx,dy,dz\n" if disp else "value\n")
            n = len(ids) - (1 if mode == "invalid" else 0)
            for j in range(n):
                v = "" if mode == "nan" else repr(float(j * src))
                if disp and oi >= len(picks) - missing:  # disp_partial: 끝 프레임은 변위 빈 칸
                    fh.write(f"{v},,,\n")
                else:
                    fh.write(f"{v},0.0,0.0,{0.01 * src}\n" if disp else f"{v}\n")
        frames.append((oi, src, f"Time = {0.001 * src:g}"))
    result("OK", nodes=len(ids), faces=2, total=total, frames=frames)
    print(f"hw (fake) contour3d OK frames={len(frames)}", flush=True)
    return 0
