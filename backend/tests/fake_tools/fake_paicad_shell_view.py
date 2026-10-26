"""가짜 paicad 쉘·뷰 명령(shell-morph.md §5, geometry-view.md §5·§6.8) — fake_paicad가 `shell <verb>`·`view …`·`shell view …`일 때 부른다.

표준 라이브러리만. 출력 이름·스키마 핵심 키는 계약과 같다(값은 합성). 실패 주입은 fake_paicad와 같은 규칙:
  FAKE_PAICAD_FAIL        `shell_extract:<code>` · `shell_fixed_scan:<code>` · `shell_tag:<code>` · `shell_update:<code>` ·
                          `shell_morph:<code>` · `shell_check:<code>` · `view_export:<code>` · `view_preview:<code>`(쉘 뷰도 같은 키)
  FAKE_PAICAD_FAIL_WHEN   `shell_update:<code>:<이름><op><값>` · `shell_check:<code>:…` · `view_preview:<code>:…`
  FAKE_PAICAD_SHELL_FEATURES  shell extract가 낼 features 배열(기본: CHASSIS_REAR 비드 B1 깊이·위치 U, B2 깊이(체결 영역과 겹침 → use_default false))
  FAKE_PAICAD_SHELL_PARTS     shell extract `parts`(기본 [{body: CHASSIS_REAR, part_id: 2001, title: CHASSIS_REAR}])
  FAKE_PAICAD_SHELL_FILE      morph가 사본으로 낼 조립 폴더 파일 상대 경로(기본: chassis.inc가 있으면 그것, 없으면 첫 *.inc)
  view grid(doe-preview.md §3, paicad 0.14.0): `view_grid:<code>`(명령 전체 FAIL — manifest 없음, VIEW_*면 종료코드 14) ·
                          `view_grid_cell:<idx>:<code>`(그 번호 셀만 FAIL, 쉼표로 여러 개 · `VIEW_*`면 셀 ERROR) · FAIL_WHEN `view_grid:<code>:<이름><op><값>`(값 조건 셀 FAIL) ·
                          NOREPORT=view_grid(종료코드 1, manifest 없음) · FAKE_PAICAD_GRID_ERROR_RAISE=<idx>(그 셀이 내부 예외 → 셀 폴더 없음 ERROR)
쉘 morph 사본 = 원본 바이트 + `#FAKE_SHELL_NODE <값 json>` 줄(실제는 /NODE 좌표 필드만 바뀜). 뷰 GLB = 삼각형 2개·바디 2개 합성 GLB.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import sys
import zlib

SHELL_BASE = {"schema_version": 1, "kind": "shell", "engine": "native"}
DEFAULT_PARTS = [{"body": "CHASSIS_REAR", "part_id": 2001, "title": "CHASSIS_REAR", "faces": 64, "edges": 210, "vertices": 150}]
DEFAULT_SHELL_FEATURES = [
    {"name": "CHASSIS_REAR_BEAD_D_1", "type": "BEAD_DEPTH", "bead": "CHASSIS_REAR_B1", "body": "CHASSIS_REAR", "nominal": 4.0,
     "unit": "mm", "range": {"min": 3.8, "max": 4.2, "ratio": 0.05}, "feasible": {"min": 1.2, "max": 6.9, "limited_by": "bottom_width",
                                                                                  "source": "estimate"},
     "group": None, "use_default": True},
    {"name": "CHASSIS_REAR_BEAD_U_1", "type": "BEAD_POS_U", "bead": "CHASSIS_REAR_B1", "body": "CHASSIS_REAR", "nominal": 35.0,
     "unit": "mm", "range": {"min": 30.0, "max": 40.0, "abs_mm": 5.0}, "group": None, "use_default": True},
    {"name": "CHASSIS_REAR_BEAD_D_2", "type": "BEAD_DEPTH", "bead": "CHASSIS_REAR_B2", "body": "CHASSIS_REAR", "nominal": 3.0,
     "unit": "mm", "range": {"min": 2.85, "max": 3.15, "ratio": 0.05}, "group": None, "use_default": False},
]


def _env_json(name, default):
    return json.loads(os.environ[name]) if os.environ.get(name) else json.loads(json.dumps(default))


def tiny_glb(nodes=("A", "B"), extra_attr=None):
    """바디마다 삼각형 1개(속성 POSITION·_FACE_ID[·_DISP_MM]) — 확장 없음, 4바이트 정렬, 결정적."""
    bin_parts, views, accessors, gnodes, meshes = [], [], [], [], []
    off = 0
    for k, name in enumerate(nodes):
        pos = struct.pack("<9f", 0, 0, k, 1, 0, k, 0, 1, k)
        fid = struct.pack("<3I", 1, 1, 1)
        datas = [(pos, "VEC3", 5126, [0.0, 0.0, float(k)], [1.0, 1.0, float(k)]), (fid, "SCALAR", 5125, None, None)]
        if extra_attr:
            datas.append((struct.pack("<3f", 0.1, 0.2, 0.3), "SCALAR", 5126, None, None))
        attrs = {}
        for j, (d, typ, ct, mn, mx) in enumerate(datas):
            views.append({"buffer": 0, "byteOffset": off, "byteLength": len(d)})
            acc = {"bufferView": len(views) - 1, "componentType": ct, "count": 3, "type": typ}
            if mn is not None:
                acc["min"], acc["max"] = mn, mx
            accessors.append(acc)
            attrs[["POSITION", "_FACE_ID", extra_attr or "_X"][j]] = len(accessors) - 1
            bin_parts.append(d)
            off += len(d)
        meshes.append({"primitives": [{"attributes": attrs, "mode": 4}]})
        gnodes.append({"name": name, "mesh": len(meshes) - 1})
    binc = b"".join(bin_parts)
    binc += b"\x00" * ((4 - len(binc) % 4) % 4)
    doc = {"asset": {"version": "2.0", "generator": "paicad fake"}, "scene": 0,
           "scenes": [{"nodes": [0]}], "nodes": [{"name": "paicad_view", "children": list(range(1, len(gnodes) + 1)),
                                                  "extras": {"unit": "mm", "up_axis": "Z"}}] + gnodes,
           "meshes": meshes, "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(binc)}]}
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binc)
    return struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js + \
        struct.pack("<II", len(binc), 0x004E4942) + binc


def main(cmd, args, flags, g):
    write_json, read_json, progress, finish = g["write_json"], g["read_json"], g["progress"], g["finish"]
    exists_exit, need, fails, fail_when, VERSION = g["exists_exit"], g["need"], g["fails"], g["fail_when"], g["VERSION"]
    CATEGORY, EXIT, ENGLISH = g["CATEGORY"], g["EXIT"], g["ENGLISH"]
    base = dict(SHELL_BASE, engine_version=VERSION)

    def fail_doc(path, code, extra=None):
        cat = CATEGORY.get(code, "INTERNAL")
        doc = dict(base, status="FAIL", code=code, category=cat, message=ENGLISH.get(code, f"fake {cmd} failure {code}"), **(extra or {}))
        write_json(path, doc)
        return EXIT.get(cat, 20)

    def out_dir(name="out-dir"):
        d = args.get(name) or sys.exit(2)
        os.makedirs(d, exist_ok=True)
        return d

    if cmd == "shell_extract":
        cad = need("cad")
        o = out_dir()
        xml, fj = os.path.join(o, "parameter_extracted.xml"), os.path.join(o, "shell_features.json")
        exists_exit([xml, fj])
        progress(20, "recognizing beads")
        code = fails("shell_extract")
        if code:
            finish("shell_features.json", "FAIL", code, fail_doc(fj, code))
        feats = _env_json("FAKE_PAICAD_SHELL_FEATURES", DEFAULT_SHELL_FEATURES)
        parts = _env_json("FAKE_PAICAD_SHELL_PARTS", DEFAULT_PARTS)
        warns = [{"code": "FIXED_INFO_MISSING", "message": "no assembly folder"}] if not args.get("assem-dir") else \
            [{"code": "BEAD_FIXED_OVERLAP", "feature": f["name"], "message": "bead covers fixed cluster"} for f in feats
             if f.get("use_default") is False]
        os.makedirs(os.path.join(o, "features"), exist_ok=True)
        for f in feats:
            f.setdefault("png", f"features/{f['name']}.png")
            with open(os.path.join(o, f["png"]), "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\nfake")
        with open(xml, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0" encoding="utf-8"?>\n<Root>\n  <Model Name="%s">\n' % os.path.basename(cad))
            for f in feats:
                fh.write("    <Parameter><Name>%s</Name><Value>%r mm</Value></Parameter>\n" % (f["name"], float(f["nominal"])))
            fh.write("  </Model>\n</Root>\n")
        write_json(fj, dict(base, unit_system="mm-ton-s", cad={"mode": "single", "files": [{"rel": os.path.basename(cad), "sha256": "0" * 64}]},
                            parts=parts, beads=[], features=feats, groups=[],
                            fixed={"available": bool(args.get("assem-dir")), "digest": "sha256:fake", "transition_mm": 6.0},
                            warnings=warns))
        finish("shell_features.json", "OK", None, 0)
    if cmd == "shell_fixed_scan":
        need("assem-dir")
        o = out_dir()
        sj, npz = os.path.join(o, "shell_scan.json"), os.path.join(o, "fixed_nodes.npz")
        exists_exit([sj, npz])
        code = fails("shell_fixed_scan")
        if code:
            finish("shell_scan.json", "FAIL", code, fail_doc(sj, code))
        parts = [p["part_id"] for p in read_json(need("features")).get("parts", [])] if args.get("features") else []
        with open(npz, "wb") as fh:
            fh.write(b"fake-npz")
        write_json(sj, dict(base, status="OK", code=None, message=None, candidates=[{"part_id": 2001, "title": "CHASSIS_REAR", "n_shell": 10}],
                            parts=parts, fixed={"digest": "sha256:fakefixed", "total": 12,
                                                "by_kind": {"INTER_TYPE2_SECONDARY": 4, "RBE2": 8}, "refs": [],
                                                "clusters": [{"id": 1, "nodes": 8, "center": [1.0, 2.0, 0.0], "radius_mm": 4.0,
                                                              "kinds": ["RBE2"]}]},
                            files={"nodes": "fixed_nodes.npz"}, warnings=[]))
        finish("shell_scan.json", "OK", None, 0)
    if cmd == "shell_tag":
        for a in ("cad", "features", "assem-dir", "fixed-dir"):
            need(a)
        o = out_dir()
        tj, npz = os.path.join(o, "shell_tag.json"), os.path.join(o, "shell_tag_nodes.npz")
        exists_exit([tj, npz])
        code = fails("shell_tag")
        if code:
            finish("shell_tag.json", "FAIL", code, fail_doc(tj, code))
        with open(npz, "wb") as fh:
            fh.write(b"fake-npz")
        write_json(tj, dict(base, status="OK", code=None, message=None, match_ratio=0.9991, parts=[], files={"nodes": "shell_tag_nodes.npz"},
                            fixed_digest="sha256:fakefixed", warnings=[]))
        finish("shell_tag.json", "OK", None, 0)
    if cmd in ("shell_update", "shell_morph", "shell_check", "shell_run"):
        return _shell_sample(cmd, args, g, base, fail_doc)
    if cmd in ("view_export", "shell_view_export"):
        need("cad")
        need("features")
        o = out_dir()
        man, glb = os.path.join(o, "view_manifest.json"), os.path.join(o, "view.glb")
        exists_exit([man, glb])
        kind = "shell" if cmd.startswith("shell") else "solid"
        code = fails("view_export")
        if code:
            finish("view_manifest.json", "FAIL", code, fail_doc(man, code, {"kind": kind, "mode": "nominal"}))
        data = tiny_glb()
        with open(glb, "wb") as fh:
            fh.write(data)
        write_json(man, dict(base, kind=kind, mode="nominal", status="OK", code=None, category=None, message=None, unit="mm", up_axis="Z",
                             glb={"file": "view.glb", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "triangles": 2,
                                  "vertices": 6},
                             tess={"linear_mm": 0.1, "angular_deg": 20.0, "coarsened": 0}, bodies=[], features=[],
                             fixed_clusters=[] if not args.get("fixed-dir") else [{"id": 1}], warnings=[]))
        finish("view_manifest.json", "OK", None, 0)
    if cmd in ("view_preview", "shell_view_preview"):
        return _preview(cmd, args, g, base, fail_doc)
    if cmd in ("view_grid", "shell_view_grid"):
        return _grid(cmd, args, g, base, fail_doc)
    sys.exit(2)


def _png(w, h, rgb):
    """w×h 단색 PNG(8비트 RGB, 결정적)."""
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    row = b"\x00" + bytes(rgb) * w
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(row * h, 6)) + chunk(b"IEND", b"")


def _grid_cell_fail(idx):
    out = {}
    for item in (os.environ.get("FAKE_PAICAD_FAIL") or "").split(","):
        parts = item.strip().split(":")
        if len(parts) == 3 and parts[0] == "view_grid_cell" and parts[1].isdigit():
            out[int(parts[1])] = parts[2]
    return out.get(idx)


def _grid(cmd, args, g, base, fail_doc):
    """`paicad view grid` · `paicad shell view grid`(doe-preview.md §3): cells.json의 셀마다 update(가짜) → cells/<id>/{preview_manifest.json,
    preview.glb(OK만), thumb.png}. grid_manifest.json 존재 = 성공(종료코드 0, 셀 상태 무관)."""
    write_json, read_json, finish, need, exists_exit, progress = (g["write_json"], g["read_json"], g["finish"], g["need"], g["exists_exit"],
                                                                  g["progress"])
    fail_when, CATEGORY, EXIT, VERSION = g["fail_when"], g["CATEGORY"], g["EXIT"], g["VERSION"]
    kind = "shell" if cmd.startswith("shell") else "solid"
    need("cad")
    names = {f["name"] for f in read_json(need("features")).get("features", [])}
    if kind == "shell":
        need("fixed-dir")
    topts = read_json(need("thumb-options"))
    doc = read_json(need("cells"))
    cells = doc.get("cells") if isinstance(doc, dict) else None
    ids = [c.get("id") for c in cells or [] if isinstance(c, dict)]
    import re

    if not cells or len(set(ids)) != len(ids) or not all(isinstance(i, str) and re.fullmatch(r"[0-9a-z_]{1,64}", i) for i in ids):
        print("PAICAD RESULT FAIL GEOM_INPUT_INVALID -", flush=True)
        sys.exit(3)
    for c in cells:
        bad = [n for n in (c.get("values") or {}) if n not in names]
        if bad:
            print("unknown name(s): " + ", ".join(bad), file=sys.stderr, flush=True)
            print("PAICAD RESULT FAIL GEOM_INPUT_INVALID -", flush=True)
            sys.exit(3)
    o = args.get("out-dir") or sys.exit(2)
    os.makedirs(o, exist_ok=True)
    gm_path, cdir = os.path.join(o, "grid_manifest.json"), os.path.join(o, "cells")
    exists_exit([gm_path, cdir])
    if os.environ.get("FAKE_PAICAD_NOREPORT") == "view_grid":
        sys.exit(1)
    whole = g["fails"]("view_grid")
    if whole:
        finish("grid_manifest.json", "FAIL", whole, EXIT.get(CATEGORY.get(whole, "INTERNAL"), 20))
    w, h = int(topts.get("w", 320)), int(topts.get("h", 240))
    os.makedirs(cdir)
    rows = []
    for idx, c in enumerate(cells):
        progress(15 + int(80 * idx / len(cells)), f"cell {idx + 1}/{len(cells)} {c['id']}")
        vals = {k: float(v) for k, v in (c.get("values") or {}).items()}
        if os.environ.get("FAKE_PAICAD_GRID_ERROR_RAISE") == str(idx):  # 셀 처리 중 내부 예외: 셀 폴더 없이 ERROR
            rows.append({"id": c["id"], "status": "ERROR", "code": "GEOM_INTERNAL", "category": "INTERNAL", "max_disp_mm": None, "total_s": 0.0})
            continue
        code = _grid_cell_fail(idx) or fail_when("view_grid", vals)
        part = os.path.join(cdir, ".part_" + c["id"])
        os.makedirs(part)
        digest = hashlib.sha256((c["id"] + json.dumps(vals, sort_keys=True)).encode()).digest()
        png = _png(w, h, (digest[0], digest[1], digest[2]) if not code else (200, 60, 60))
        max_mm = None if code else round(sum(abs(v) for v in vals.values()) % 3.0, 3)
        man = dict(base, kind=kind, mode="preview", values=vals, status="FAIL" if code else "OK", code=code,
                   category=CATEGORY.get(code, "INTERNAL") if code else None, message=f"fake grid cell failure {code}" if code else None,
                   fe={"mode": "off"}, reports={"update": "update/update.json", "morph": None, "check": None},
                   failure={"features": list(vals)[:2], "clusters": [], "points": []} if code else None,
                   timing={"update_s": 0.1, "tess_s": 0.1, "total_s": 0.2},
                   thumb={"file": "thumb.png", "sha256": hashlib.sha256(png).hexdigest(), "w": w, "h": h, "clipped": False})
        if code:
            man.update(glb=None, disp=None)
        else:
            data = tiny_glb(extra_attr="_DISP_MM")
            with open(os.path.join(part, "preview.glb"), "wb") as fh:
                fh.write(data)
            man.update(glb={"file": "preview.glb", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "triangles": 2},
                       disp={"attribute": "_DISP_MM", "max_mm": max_mm, "by_face": {}})
        with open(os.path.join(part, "thumb.png"), "wb") as fh:
            fh.write(png)
        write_json(os.path.join(part, "preview_manifest.json"), man)
        os.replace(part, os.path.join(cdir, c["id"]))
        st = "OK" if not code else ("ERROR" if code.startswith("VIEW_") else "FAIL")
        rows.append({"id": c["id"], "status": st, "code": code, "category": CATEGORY.get(code, "INTERNAL") if code else None,
                     "max_disp_mm": max_mm, "total_s": 0.1})
    write_json(gm_path, dict(base, kind=kind, camera={"view_dir": topts.get("view_dir"), "center": [0.0, 0.0, 0.0], "scale": 1.0,
                                                      "digest": hashlib.sha256(json.dumps(topts, sort_keys=True).encode()).hexdigest()},
                             disp_range_mm=topts.get("disp_range_mm"), nominal={"bbox": [0, 0, 0, 1, 1, 1], "view_sha256": "0" * 64},
                             cells=rows, timing={"load_s": 0.1, "total_s": 0.2}))
    progress(100, "grid done")
    finish("grid_manifest.json", "OK", None, 0)


def _preview(cmd, args, g, base, fail_doc):
    write_json, read_json, finish, need, exists_exit = g["write_json"], g["read_json"], g["finish"], g["need"], g["exists_exit"]
    fails, fail_when, CATEGORY, EXIT = g["fails"], g["fail_when"], g["CATEGORY"], g["EXIT"]
    need("cad")
    need("features")
    vals = read_json(need("values")).get("values") or {}
    o = args.get("out-dir") or sys.exit(2)
    os.makedirs(o, exist_ok=True)
    man = os.path.join(o, "preview_manifest.json")
    exists_exit([man])
    fe = args.get("fe") or "off"
    kind = "shell" if cmd.startswith("shell") else "solid"
    if fe != "off" and not args.get("assem-dir"):
        sys.exit(2)
    code = fails("view_preview") or fail_when("view_preview", vals)
    doc = dict(base, kind=kind, mode="preview", values=vals, status="OK", code=None, category=None, message=None,
               nominal_ref={"view_sha256": None, "tess": {"linear_mm": 0.1, "angular_deg": 20.0}}, fe={"mode": fe},
               reports={"update": "update/update.json", "morph": None, "check": None}, failure=None,
               timing={"update_s": 0.1, "tess_s": 0.1, "morph_s": None, "check_s": None, "total_s": 0.2})
    if code:
        cat = CATEGORY.get(code, "INTERNAL")
        doc.update(status="FAIL", code=code, category=cat, message=f"fake preview failure {code}", glb=None, disp=None,
                   failure={"features": list(vals)[:2], "clusters": [], "points": []})
        write_json(man, doc)
        finish("preview_manifest.json", "FAIL", code, EXIT.get(cat, 20) if cat != "CAD_FAILED" else 10)
    data = tiny_glb(extra_attr="_DISP_MM")
    with open(os.path.join(o, "preview.glb"), "wb") as fh:
        fh.write(data)
    doc["glb"] = {"file": "preview.glb", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "triangles": 2}
    doc["disp"] = {"attribute": "_DISP_MM", "max_mm": 0.3, "by_face": {}}
    if fe != "off":
        fed = tiny_glb(nodes=("FE",), extra_attr="_DISP_MM")
        with open(os.path.join(o, "preview_fe.glb"), "wb") as fh:
            fh.write(fed)
        doc["fe"] = {"mode": fe, "status": "PASS", "code": None, "category": None,
                     "glb": {"file": "preview_fe.glb", "sha256": hashlib.sha256(fed).hexdigest(), "bytes": len(fed)}, "max_disp_mm": 0.31}
    write_json(man, doc)
    finish("preview_manifest.json", "OK", None, 0)


def _assem_file(assem):
    want = os.environ.get("FAKE_PAICAD_SHELL_FILE")
    if want:
        return want
    if os.path.isfile(os.path.join(assem, "chassis.inc")):
        return "chassis.inc"
    incs = sorted(n for n in os.listdir(assem) if n.lower().endswith(".inc"))
    return incs[0] if incs else None


def _shell_sample(cmd, args, g, base, fail_doc):
    write_json, read_json, finish, need, exists_exit, progress = (g["write_json"], g["read_json"], g["finish"], g["need"], g["exists_exit"],
                                                                  g["progress"])
    fails, fail_when, CATEGORY = g["fails"], g["fail_when"], g["CATEGORY"]

    def values():
        return read_json(need("values")).get("values") or {}

    def update(d):
        need("cad")
        names = {f["name"] for f in read_json(need("features"))["features"]}
        os.makedirs(d, exist_ok=True)
        uj = os.path.join(d, "shell_update.json")
        exists_exit([uj, os.path.join(d, "sample.brep")])
        vals = values()
        unknown = [n for n in vals if n not in names]
        if unknown:
            return fail_doc(uj, "GEOM_INPUT_INVALID", {"message": "unknown name(s): " + ", ".join(unknown)}), "GEOM_INPUT_INVALID"
        code = fails("shell_update") or fail_when("shell_update", vals)
        if code:
            return fail_doc(uj, code, {"fixed_precheck": {"status": "FAIL" if code == "SHELL_FIXED_REGION_VIOLATION" else "PASS"}}), code
        with open(os.path.join(d, "sample.brep"), "wb") as fh:
            fh.write(b"fake-sheet:" + json.dumps(vals, sort_keys=True).encode())
        write_json(os.path.join(d, "face_map.json"), {})
        write_json(uj, dict(base, status="OK", code=None, category=None, message=None, values=vals, applied=[], changed={},
                            fixed_precheck={"status": "PASS" if args.get("fixed-dir") else "NOT_EVALUATED", "violations": 0},
                            elapsed_s=0.1))
        return 0, None

    def morph(d, upd):
        for a in ("assem-dir", "tag-dir", "fixed-dir", "features"):
            need(a)
        os.makedirs(d, exist_ok=True)
        mj = os.path.join(d, "shell_morph.json")
        exists_exit([mj, os.path.join(d, "files")])
        vals = (read_json(os.path.join(upd, "shell_update.json")).get("values") or {}) if os.path.isfile(os.path.join(upd, "shell_update.json")) else {}
        code = fails("shell_morph") or fail_when("shell_morph", vals)
        if code:
            return fail_doc(mj, code), code
        rel = _assem_file(args["assem-dir"])
        files = []
        if rel and vals:
            with open(os.path.join(args["assem-dir"], rel), "rb") as fh:
                data = fh.read()
            out = data + ("#FAKE_SHELL_NODE " + json.dumps(vals, sort_keys=True) + "\n").encode()
            dst = os.path.join(d, "files", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(out)
            files.append({"rel": rel, "sha256_in": hashlib.sha256(data).hexdigest(), "sha256_out": hashlib.sha256(out).hexdigest(),
                          "moved_nodes": 10})
        write_json(mj, dict(base, status="OK", code=None, category=None, message=None, max_disp_mm=0.4, files=files, parts=[], elapsed_s=0.2))
        return 0, None

    def check(d, upd, mor, files_dir):
        for a in ("assem-dir", "tag-dir", "fixed-dir", "features"):
            need(a)
        os.makedirs(d, exist_ok=True)
        cj = os.path.join(d, "shell_check.json")
        exists_exit([cj])
        vals = values()
        code = fails("shell_check") or fail_when("shell_check", vals)
        thickness = read_json(args["thickness"]) if args.get("thickness") else None
        if code:
            return fail_doc(cj, code, {"checks": {}, "warnings": [], "out_files": [], "thickness": thickness}), code, []
        rels = [f["rel"] for f in (read_json(os.path.join(mor, "shell_morph.json")).get("files") or [])]
        for rel in rels:
            dst = os.path.join(files_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(mor, "files", rel), dst)
        write_json(cj, dict(base, status="PASS", code=None, category=None, message=None,
                            checks={"fixed": {"status": "PASS", "moved_fixed_nodes": 0, "max_mm": 0.0},
                                    "quality": {"status": "PASS", "max_warpage_deg": 6.1, "min_jacobian": 0.71}},
                            warnings=[], options={}, out_files=rels, thickness=thickness, elapsed_s=0.3))
        return 0, None, rels

    if cmd == "shell_update":
        rc, code = update(args.get("out-dir") or sys.exit(2))
        finish("shell_update.json", "FAIL" if code else "OK", code, rc)
    if cmd == "shell_morph":
        rc, code = morph(args.get("out-dir") or sys.exit(2), args["update-dir"])
        finish("shell_morph.json", "FAIL" if code else "OK", code, rc)
    if cmd == "shell_check":
        rc, code, _r = check(args.get("out-dir") or sys.exit(2), args["update-dir"], args["morph-dir"], args["out-files-dir"])
        finish("shell_check.json", "FAIL" if code else "PASS", code, rc)
    stages, fail, rels = [], None, []
    for name in ("update", "morph", "check"):
        progress({"update": 20, "morph": 60, "check": 90}[name], f"shell run {name}")
        if name == "update":
            rc, code = update(args["update-dir"])
        elif name == "morph":
            rc, code = morph(args["morph-dir"], args["update-dir"])
        else:
            rc, code, rels = check(args["check-dir"], args["update-dir"], args["morph-dir"], args["out-files-dir"])
        stages.append({"step": name, "exit_code": rc, "status": "FAIL" if code else "OK", "code": code})
        if code:
            fail = {"code": code, "category": CATEGORY.get(code), "message": f"fake {name} failure", "step": name, "report": None, "rc": rc}
            break
    os.makedirs(args["check-dir"], exist_ok=True)
    stat = "FAIL" if fail else "PASS"
    write_json(os.path.join(args["check-dir"], "shell_run.json"),
               dict(base, status=stat, code=fail["code"] if fail else None, category=fail["category"] if fail else None,
                    message=fail["message"] if fail else None, stages=stages,
                    skip={k: fail[k] for k in ("code", "category", "message", "step", "report")} if fail else None,
                    out_files=rels if not fail else []))
    finish("shell_run.json", stat, fail["code"] if fail else None, fail["rc"] if fail else 0)
