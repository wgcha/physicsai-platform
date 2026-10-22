"""가짜 paicad 조립 매칭 명령(asm-match.md §4·§5, paicad 0.13.0) — fake_paicad가 `asm parts|check|write`일 때 부른다.

표준 라이브러리만. include 트리 규칙·digest는 플랫폼 `physicsai_core/geometry/asm_tree.py`와 같다(그래서 STALE이 거짓 양성이 안 된다).
  - starter = 조립 폴더 직계 `*.rad` 중 `/BEGIN` 줄이 있는 파일 정확히 1개(`eps_mesh*` 제외). `#include <경로>` 줄을 깊이 우선으로 따라간다.
  - parts = 트리의 `/PART/<pid>`(다음 줄 = 제목)와 `/TETRA4/<pid>` 블록 유무(`solid_ok`). 다른 요소 키워드(`/SHELL/<pid>`)만 있으면 solid_ok false.
  - bodies = `--features`의 피처 `body` 고유값(없으면 FAKE_PAICAD_ASM_BODIES JSON, 기본 ["A","B"]). recommend = i번째 바디 ↔ i번째 solid PART.
환경변수
  FAKE_PAICAD_FAIL   `asm_parts:<code>` · `asm_check:<code>`(rows 있는 FAIL, 종료코드 15) · `asm_check_norows:<code>`(rows 없는 FAIL) · `asm_write:<code>`
출력: asm_parts.json · asm_check.json(+ worst_<body>.npz·match_fe.glb) · asm_write.json(+ 트리 사본). 종료코드 FAIL = 15(EXIT_ASM) 또는 3(입력).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import sys
import zipfile

INC_RE = re.compile(r"^\s*#include\s+[\"']?([^\"'\r\n]+?)[\"']?\s*$", re.I)


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _tree(assem):
    """(starter, [{rel, sha256, includes, path}]) — 오류는 (code, message) 튜플 예외."""
    cands = []
    for n in sorted(os.listdir(assem)):
        p = os.path.join(assem, n)
        if n.lower().endswith(".rad") and not n.lower().startswith("eps_mesh") and os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as fh:
                if any(ln.strip() == "/BEGIN" for ln in fh):
                    cands.append(n)
    if len(cands) != 1:
        raise _Err("GEOM_INPUT_INVALID", f"exactly one starter with /BEGIN required (found {len(cands)})", 3)
    root_real = os.path.realpath(assem)
    files, seen = [], set()

    def visit(path, rel, stack):
        tf = {"rel": rel, "sha256": _sha(path), "includes": [], "path": path}
        seen.add(rel)
        files.append(tf)
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        for ln in lines:
            m = INC_RE.match(ln)
            if not m:
                continue
            raw = m.group(1).strip()
            target = os.path.join(os.path.dirname(path), raw.replace("\\", "/"))
            real = os.path.realpath(target)
            trel = os.path.relpath(real, root_real).replace(os.sep, "/")
            if os.path.islink(target) or trel == ".." or trel.startswith("../"):
                raise _Err("ASM_INCLUDE_OUTSIDE", f"include {raw!r} outside the assembly folder", 15)
            if not os.path.isfile(real):
                raise _Err("ASM_INCLUDE_MISSING", f"include {raw!r} target missing", 15)
            if trel in stack or trel in seen:
                raise _Err("GEOM_INPUT_INVALID", f"{trel} included twice or circular", 3)
            tf["includes"].append(trel)
            visit(os.path.join(root_real, *trel.split("/")), trel, stack + [trel])

    visit(os.path.join(root_real, cands[0]), cands[0], [cands[0]])
    return cands[0], files


def _digest(files):
    h = hashlib.sha256()
    for rel, sha in sorted((f["rel"], f["sha256"]) for f in files):
        h.update(f"{rel}\t{sha}\n".encode())
    return "sha256:" + h.hexdigest()


class _Err(Exception):
    def __init__(self, code, message, rc):
        super().__init__(message)
        self.code, self.message, self.rc = code, message, rc


def _scan_parts(files):
    parts = {}
    for f in files:
        with open(f["path"], encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        for i, ln in enumerate(lines):
            m = re.match(r"^/PART/(\d+)", ln)
            if m:
                p = parts.setdefault(int(m.group(1)), {"pid": int(m.group(1)), "title": "", "def_file": None, "elem_files": [], "node_files": [],
                                                       "tet": False, "other": False})
                p["title"], p["def_file"] = (lines[i + 1].strip() if i + 1 < len(lines) else ""), f["rel"]
            m = re.match(r"^/(TETRA4|SHELL|BRICK|SH3N)/(\d+)", ln)
            if m:
                p = parts.setdefault(int(m.group(2)), {"pid": int(m.group(2)), "title": "", "def_file": None, "elem_files": [], "node_files": [],
                                                       "tet": False, "other": False})
                if m.group(1) == "TETRA4":
                    p["tet"] = True
                else:
                    p["other"] = True
                if f["rel"] not in p["elem_files"]:
                    p["elem_files"].append(f["rel"])
        if any(ln.startswith("/NODE") for ln in lines):
            for p in parts.values():
                if p["tet"] and f["rel"] not in p["node_files"]:
                    p["node_files"].append(f["rel"])
    return parts


def _fail(path, status_extra, code, message, rc, report):
    doc = {"schema_version": 1, "engine": "native", "engine_version": os.environ.get("FAKE_PAICAD_VERSION", "0.13.0"), "status": "FAIL",
           "code": code, "category": "ASM" if rc == 15 else "INPUT", "message": message, **status_extra}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print(f"PAICAD RESULT FAIL {code} {report}", flush=True)
    sys.exit(rc)


def _env_fail(key):
    for item in (os.environ.get("FAKE_PAICAD_FAIL") or "").split(","):
        k, _, c = item.partition(":")
        if k.strip() == key:
            return c.strip()
    return None


def _exists_exit(paths):
    for p in paths:
        if os.path.exists(p):
            print(f"output exists: {p}", file=sys.stderr, flush=True)
            print("PAICAD RESULT FAIL GEOM_OUTPUT_EXISTS -", flush=True)
            sys.exit(3)


def _npy(values, descr, shape):
    head = "{'descr': '%s', 'fortran_order': False, 'shape': %s, }" % (descr, shape)
    pad = (64 - (10 + len(head) + 1) % 64) % 64
    head = head + " " * pad + "\n"
    code = "q" if descr == "<i8" else "d"
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(head)) + head.encode("latin1") + struct.pack(f"<{len(values)}{code}", *values)


def _write_npz(path, node_id, xyz, dist):
    n = len(node_id)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("node_id.npy", _npy(node_id, "<i8", f"({n},)"))
        z.writestr("xyz.npy", _npy([c for p in xyz for c in p], "<f8", f"({n}, 3)"))
        z.writestr("dist.npy", _npy(dist, "<f8", f"({n},)"))


def _ver():
    return os.environ.get("FAKE_PAICAD_VERSION", "0.13.0")


def do_parts(args):
    assem, out = args.get("assem-dir"), args.get("out-dir")
    if not assem or not out or not os.path.isdir(assem):
        print("PAICAD RESULT FAIL GEOM_INPUT_INVALID -", flush=True)
        sys.exit(3)
    os.makedirs(out, exist_ok=True)
    rep = os.path.join(out, "asm_parts.json")
    _exists_exit([rep])
    code = _env_fail("asm_parts")
    if code:
        _fail(rep, {"assem": None, "bodies": [], "parts": [], "recommend": [], "warnings": []}, code, f"fake asm parts failure {code}", 15,
              "asm_parts.json")
    try:
        starter, files = _tree(assem)
    except _Err as exc:
        _fail(rep, {"assem": None, "bodies": [], "parts": [], "recommend": [], "warnings": []}, exc.code, exc.message, exc.rc, "asm_parts.json")
    parts = _scan_parts(files)
    solid = sorted(p["pid"] for p in parts.values() if p["tet"] and not p["other"])
    if not solid:
        _fail(rep, {"assem": None, "bodies": [], "parts": [], "recommend": [], "warnings": []}, "ASM_NO_SOLID_PART", "no TETRA4 part", 15, "asm_parts.json")
    if args.get("features"):
        with open(args["features"], encoding="utf-8") as fh:
            doc = json.load(fh)
        names = list(dict.fromkeys(str(f.get("body")) for f in doc.get("features") or [] if f.get("body")))
    else:
        names = []
    names = names or json.loads(os.environ.get("FAKE_PAICAD_ASM_BODIES") or '["A","B"]')
    rows = [{"pid": p["pid"], "title": p["title"], "def_file": p["def_file"], "elem_files": p["elem_files"], "node_files": p["node_files"],
             "elems": {"TETRA4": 10} if p["tet"] else {"SHELL": 10}, "nodes": 8, "volume": 100.0 if p["tet"] else None,
             "bbox": [0, 0, 0, 1, 1, 1], "solid_ok": bool(p["tet"] and not p["other"])} for p in sorted(parts.values(), key=lambda q: q["pid"])]
    doc = {"schema_version": 1, "engine": "native", "engine_version": _ver(), "status": "OK", "code": None, "message": None,
           "assem": {"digest": _digest(files), "starter": starter,
                     "tree": [{k: v for k, v in f.items() if k != "path"} for f in files], "cache": {"hits": 0, "misses": len(files)}},
           "bodies": [{"body": n, "volume": 100.0, "bbox": [0, 0, 0, 1, 1, 1]} for n in names], "parts": rows,
           "recommend": [{"body": n, "pids": [solid[i]], "score": 0.9, "basis": {"bbox_iou": 0.9, "volume_ratio": 1.0, "name": 0.0, "renum": False}}
                         for i, n in enumerate(names) if i < len(solid)], "warnings": []}
    cache = args.get("cache-dir")
    if cache:
        os.makedirs(cache, exist_ok=True)
        with open(os.path.join(cache, "fake.idx"), "w", encoding="utf-8") as fh:
            fh.write("cache")
    with open(rep, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print("PAICAD PROGRESS 100 parts done", flush=True)
    print("PAICAD RESULT OK - asm_parts.json", flush=True)
    sys.exit(0)


def do_check(args):
    assem, out, mpath = args.get("assem-dir"), args.get("out-dir"), args.get("match")
    if not assem or not out or not mpath or not os.path.isfile(mpath) or not os.path.isdir(assem):
        print("PAICAD RESULT FAIL GEOM_INPUT_INVALID -", flush=True)
        sys.exit(3)
    os.makedirs(out, exist_ok=True)
    rep, glb = os.path.join(out, "asm_check.json"), os.path.join(out, "match_fe.glb")
    _exists_exit([rep, glb])
    with open(mpath, "rb") as fh:
        raw = fh.read()
    sha = hashlib.sha256(raw).hexdigest()
    match = json.loads(raw)
    norows = _env_fail("asm_check_norows")
    if norows:
        _fail(rep, {"rows_sha256": sha, "rows": []}, norows, f"fake asm check failure {norows}", 15, "asm_check.json")
    try:
        starter, files = _tree(assem)
    except _Err as exc:
        _fail(rep, {"rows_sha256": sha}, exc.code, exc.message, exc.rc, "asm_check.json")
    code = _env_fail("asm_check")
    rows = []
    for r in match.get("rows") or []:
        body = str(r["body"])
        fname = f"worst_{re.sub(r'[^A-Za-z0-9_.-]', '_', body)}.npz"
        _write_npz(os.path.join(out, fname), [1000 + i for i in range(3)], [[0.0, 0.0, 0.1 * i] for i in range(3)], [0.04, 0.02, 0.01])
        bad = bool(code)
        rows.append({"body": body, "pids": r["pids"], "status": "FAIL" if bad else "PASS", "code": code if bad else None, "skin_nodes": 100,
                     "match_ratio": 0.5 if bad else 0.9995, "tol_mm": 0.05, "dist_mm": {"mean": 0.003, "p95": 0.011, "p99": 0.019, "max": 0.041},
                     "bbox_delta_mm": [0.0] * 6, "faces": {"total": 6, "uncovered": []}, "shared": {"nodes": 0, "parts": []},
                     "worst": {"count": 3, "file": fname}, "suggest": None})
    with open(glb, "wb") as fh:
        fh.write(b"glTF" + b"\x02\x00\x00\x00" + struct.pack("<I", 12))
    doc = {"schema_version": 1, "engine": "native", "engine_version": _ver(), "status": "FAIL" if code else "PASS", "code": code,
           "category": "ASM" if code else None, "message": f"fake {code}" if code else None, "rows_sha256": sha,
           "assem": {"digest": _digest(files), "node_files": [{"rel": f["rel"], "nodes": 8} for f in files], "elem_files": [f["rel"] for f in files]},
           "tolerance": {"abs_mm": 0.05, "rel": 1e-4, "min_match_ratio": 0.98}, "rows": rows,
           "file_checks": {"shared_nodes": 0, "duplicate_node_defs": 0, "duplicate_parts": []},
           "glb": {"file": "match_fe.glb", "sha256": _sha(glb)}, "warnings": [], "elapsed_s": 0.1}
    with open(rep, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print(f"PAICAD RESULT {doc['status']} {code or '-'} asm_check.json", flush=True)
    sys.exit(15 if code else 0)


def do_write(args):
    assem, out, mpath = args.get("assem-dir"), args.get("out-dir"), args.get("asm-match")
    if not assem or not out or not mpath or not os.path.isfile(mpath):
        print("PAICAD RESULT FAIL GEOM_INPUT_INVALID -", flush=True)
        sys.exit(3)
    if os.path.commonpath([os.path.realpath(out), os.path.realpath(assem)]) == os.path.realpath(assem):
        print("PAICAD RESULT FAIL GEOM_INPUT_INVALID -", flush=True)
        sys.exit(3)
    os.makedirs(out, exist_ok=True)
    rep = os.path.join(out, "asm_write.json")
    _exists_exit([rep])
    code = _env_fail("asm_write")
    if code:
        _fail(rep, {"files": []}, code, f"fake asm write failure {code}", 15, "asm_write.json")
    try:
        starter, files = _tree(assem)
    except _Err as exc:
        _fail(rep, {"files": []}, exc.code, exc.message, exc.rc, "asm_write.json")
    patch = args.get("patch")
    outs = []
    for f in files:
        dst = os.path.join(out, *f["rel"].split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(f["path"], "rb") as fh:
            data = fh.read()
        changed = 0
        if patch and f["rel"] == starter:  # 실제는 노드 정의 파일의 /NODE 좌표 줄만 바뀐다 — 가짜는 starter 끝에 표시 줄
            data += f"#FAKE_PATCH {_sha(patch)[:12]}\n".encode()
            changed = 1
        with open(dst, "wb") as fh:
            fh.write(data)
        outs.append({"rel": f["rel"], "changed_lines": changed})
    doc = {"schema_version": 1, "engine": "native", "engine_version": _ver(), "status": "OK", "code": None, "message": None,
           "assem": {"digest": _digest(files), "starter": starter}, "files": outs, "nodes_written": 1 if patch else 0, "elapsed_s": 0.01}
    with open(rep, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print("PAICAD RESULT OK - asm_write.json", flush=True)
    sys.exit(0)


def main(cmd, args):
    {"asm_parts": do_parts, "asm_check": do_check, "asm_write": do_write}[cmd](args)
