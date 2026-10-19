"""``paicad selftest`` - site acceptance kit, minimal version (contract section 9 stage 0 (b)).

Runs on the real nominal CAD + baseline include + assembly folder: extract -> tag -> nominal update ->
morph -> check -> short envelope, each into ``<out-dir>/work/<stage>/`` (site-local working files),
and writes ``selftest_report.json`` / ``selftest_report.md`` with **numbers only**: no CAD or mesh
content, no coordinates, no node or element ids (the report is what the user sends back).

Report sections: tag unclassified (unmatched) boundary nodes and match ratio, unchanged round trip
byte identity (writer and nominal morph), nominal check metrics, short envelope summary.
Exit code 0 when the report is written (stage failures are recorded in it).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .common import EXIT_OK, OutDir, Reporter, StageReporter, dumps, envelope, rnd, sha256_file

REPORT_JSON = "selftest_report.json"
REPORT_MD = "selftest_report.md"
WORK = "work"


def _sha_input(p: Path) -> str | None:
    if p.is_file():
        return sha256_file(p)
    if p.is_dir():
        import hashlib

        h = hashlib.sha256()
        for f in sorted(x for x in p.rglob("*") if x.is_file()):
            h.update(f.relative_to(p).as_posix().encode())
            h.update(sha256_file(f).encode())
        return h.hexdigest()
    return None


def _read(p: Path) -> dict | None:
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def run(args, rep: Reporter) -> int:
    from .cli import guarded, versions
    from .mesh.radioss import rewrite_nodes

    t0 = time.monotonic()
    out = OutDir(args.out_dir, [REPORT_JSON, REPORT_MD, WORK])
    out.prepare()
    root = Path(args.out_dir)
    work = root / WORK
    work.mkdir(parents=True, exist_ok=True)
    common = dict(options=args.options, threads=args.threads, body_map=args.body_map, _nested=True)
    stages: dict[str, dict] = {}

    def stage(name: str, ns: argparse.Namespace, lo: int, hi: int, report: str | None) -> dict | None:
        srep = StageReporter(Path(ns.out_dir), rep, name, lo, hi)
        try:
            code, err, _msg = guarded(ns, srep)
        finally:
            srep.close()
        d = _read(Path(ns.out_dir) / report) if report else None
        stages[name] = {"exit_code": code, "status": (d or {}).get("status") or ("OK" if code == 0 else "FAIL"), "code": (d or {}).get("code") or err}
        return d

    ex, tg = work / "extract", work / "tag"
    feats = ex / "parameter_features.json"
    stage("extract", argparse.Namespace(cmd="extract", cad=args.cad, out_dir=str(ex), renum_csv=args.renum_csv, no_png=True, **common), 0, 15, None)
    fdoc = _read(feats) if stages["extract"]["exit_code"] == 0 else None
    tdoc = None
    if fdoc:
        tdoc = stage(
            "tag",
            argparse.Namespace(
                cmd="tag", cad=args.cad, features=str(feats), baseline_inc=args.baseline_inc, renum_csv=args.renum_csv, assem_dir=args.assem_dir, out_dir=str(tg), **common
            ),
            15,
            35,
            "tag.json",
        )
    ok_tag = stages.get("tag", {}).get("exit_code") == 0
    base_bytes = Path(args.baseline_inc).read_bytes()
    roundtrip = {"writer_byte_identical": rewrite_nodes(base_bytes, {}) == base_bytes, "nominal_morph_byte_identical": None}
    cdoc = env = None
    if ok_tag:
        vals = work / "values_nominal.json"
        vals.write_text(json.dumps({"schema_version": 1, "values": {}}), encoding="utf-8")
        upd, mor, chk = work / "update_nominal", work / "morph_nominal", work / "check_nominal"
        stage("update", argparse.Namespace(cmd="update", cad=args.cad, features=str(feats), values=str(vals), out_dir=str(upd), tag_dir=str(tg), **common), 35, 45, "update.json")
        if stages["update"]["exit_code"] == 0:
            stage(
                "morph",
                argparse.Namespace(cmd="morph", baseline_inc=args.baseline_inc, tag_dir=str(tg), features=str(feats), update_dir=str(upd), out_dir=str(mor), solver=None, sweep=False, **common),
                45,
                60,
                "morph.json",
            )
        if stages.get("morph", {}).get("exit_code") == 0:
            roundtrip["nominal_morph_byte_identical"] = (mor / "morphed.inc").read_bytes() == base_bytes
            cdoc = stage(
                "check",
                argparse.Namespace(
                    cmd="check",
                    baseline_inc=args.baseline_inc,
                    morph_dir=str(mor),
                    update_dir=str(upd),
                    tag_dir=str(tg),
                    features=str(feats),
                    values=str(vals),
                    assem_dir=args.assem_dir,
                    renum_csv=args.renum_csv,
                    out_dir=str(chk),
                    out_inc=str(work / "check_nominal_out" / Path(args.baseline_inc).name),
                    **common,
                ),
                60,
                70,
                "check.json",
            )
        if not args.no_envelope and stages["update"]["exit_code"] == 0:
            envd = work / "envelope"
            ns = argparse.Namespace(
                cmd="morph",
                baseline_inc=args.baseline_inc,
                tag_dir=str(tg),
                features=str(feats),
                update_dir=str(upd),
                out_dir=str(envd),
                solver=None,
                sweep=True,
                steps=args.envelope_steps,
                pos_steps=getattr(args, "envelope_pos_steps", None) or "1,3",
                params=args.envelope_params,
                stop_after_fail=args.stop_after_fail,
                check="on",
                keep_steps=False,
                **common,
            )
            env = stage("envelope", ns, 70, 98, "envelope.json")
    v = versions()
    report = envelope(
        status="OK",
        kind="selftest",
        versions={k: v.get(k) for k in ("paicad", "ocp", "numpy", "scipy", "python")},
        inputs={
            "cad_sha256": _sha_input(Path(args.cad)),
            "baseline_sha256": sha256_file(args.baseline_inc),
            "baseline_bytes": len(base_bytes),
            "renum_sha256": sha256_file(args.renum_csv) if Path(args.renum_csv).is_file() else None,
        },
        stages=stages,
        extract=_extract_summary(fdoc),
        tag=_tag_summary(tdoc),
        roundtrip=roundtrip,
        nominal_check=_check_summary(cdoc),
        envelope=_envelope_summary(env),
        elapsed_s=rnd(time.monotonic() - t0, 3),
    )
    out.write_text(REPORT_JSON, dumps(report))
    out.write_text(REPORT_MD, render_md(report))
    out.commit([REPORT_JSON, REPORT_MD])
    rep.progress(100, "selftest report written")
    rep.result("OK", None, REPORT_JSON)
    return EXIT_OK


def _extract_summary(d: dict | None) -> dict | None:
    if not d:
        return None
    by_type: dict[str, int] = {}
    for f in d.get("features") or []:
        by_type[f["type"]] = by_type.get(f["type"], 0) + 1
    grouped = {m for g in d.get("groups") or [] for m in g["members"]}
    reps = {g["parameter"] for g in d.get("groups") or []}
    params = sum(1 for f in d.get("features") or [] if f["name"] in reps or f["name"] not in grouped)
    return {"bodies": len(d.get("bodies") or []), "features": len(d.get("features") or []), "parameters": params, "groups": len(d.get("groups") or []), "by_type": dict(sorted(by_type.items()))}


def _tag_summary(d: dict | None) -> dict | None:
    if not d:
        return None
    parts = []
    for p in d.get("parts") or []:
        c = p.get("classified") or {}
        parts.append(
            {
                "part": p.get("part"),
                "nodes": p.get("nodes"),
                "boundary_nodes": p.get("boundary_nodes"),
                "unclassified": c.get("unmatched"),
                "vertex": c.get("vertex"),
                "edge": c.get("edge"),
                "face": c.get("face"),
                "dist_max_mm": (p.get("dist_mm") or {}).get("max"),
            }
        )
    return {
        "status": d.get("status"),
        "match_ratio": d.get("match_ratio"),
        "unclassified_total": sum(int(p["unclassified"] or 0) for p in parts),
        "contacts": len(d.get("contacts") or []),
        "parts": parts,
    }


QUALITY_KEYS = (
    "inverted",
    "min_stretch",
    "baseline_min_stretch",
    "max_aspect",
    "baseline_max_aspect",
    "min_edge_mm",
    "baseline_min_edge_mm",
    "edge_ratio",
    "dt_ratio",
    "baseline_status",
)


def _check_summary(d: dict | None) -> dict | None:
    if not d:
        return None
    ch = d.get("checks") or {}
    items = (ch.get("param") or {}).get("items") or []
    errs = [it["err"] for it in items if it.get("err") is not None]
    q = ch.get("quality") or {}
    return {
        "status": d.get("status"),
        "code": d.get("code"),
        "param_items": len(items),
        "param_unmeasured": sum(1 for it in items if it.get("err") is None),
        "param_max_err_mm": max(errs) if errs else None,
        "deviation_max_mm": (ch.get("deviation") or {}).get("max_mm"),
        "quality": {k: q.get(k) for k in QUALITY_KEYS},
        "interference": (ch.get("interference") or {}).get("status"),
        "tie": (ch.get("tie") or {}).get("status"),
        "warnings": sorted({w.get("code") for w in d.get("warnings") or [] if w.get("code")}),
    }


def _envelope_summary(d: dict | None) -> dict | None:
    if not d:
        return None
    out = []
    for s in d.get("summary") or []:
        lm = s.get("limit_metric") or {}
        out.append(
            {
                "param": s["param"],
                "unit": s.get("unit", "%"),
                "last_ok": s.get("last_ok", s.get("last_ok_pct")),
                "first_fail": s.get("first_fail", s.get("first_fail_pct")),
                "first_fail_code": s["first_fail_code"],
                "limit_metric": {k: (lm.get(k) or {}).get("metric") for k in ("+", "-")},
            }
        )
    rows = d.get("rows") or []
    return {"steps_pct": d.get("steps_pct"), "pos_steps_mm": d.get("pos_steps_mm"), "steps_run": len(rows), "steps_failed": sum(1 for r in rows if r["status"] == "FAIL"), "params": out}


def _v(x) -> str:
    return "-" if x is None else str(x)


def render_md(r: dict) -> str:
    L = [
        "# paicad selftest report (numbers only)",
        "",
        f"- engine_version: {r['engine_version']}; ocp {r['versions'].get('ocp')}; python {r['versions'].get('python')}",
        f"- elapsed_s: {r['elapsed_s']}",
        "",
        "## Stages",
        "",
        "| stage | exit | status | code |",
        "|---|---|---|---|",
    ]
    for k, s in r["stages"].items():
        L.append(f"| {k} | {s['exit_code']} | {_v(s['status'])} | {_v(s['code'])} |")
    e = r.get("extract")
    if e:
        L += ["", "## Extract", "", f"- bodies {e['bodies']}, features {e['features']}, parameters {e['parameters']}, groups {e['groups']}"]
        L.append("- by type: " + ", ".join(f"{k} {v}" for k, v in e["by_type"].items()))
    t = r.get("tag")
    if t:
        L += ["", "## Tag", "", f"- match_ratio {t['match_ratio']}, unclassified boundary nodes {t['unclassified_total']}, contact faces {t['contacts']}", ""]
        L += ["| part | nodes | boundary | unclassified | max dist mm |", "|---|---|---|---|---|"]
        for p in t["parts"]:
            L.append(f"| {p['part']} | {p['nodes']} | {p['boundary_nodes']} | {p['unclassified']} | {p['dist_max_mm']} |")
    rt = r["roundtrip"]
    L += ["", "## Unchanged round trip", "", f"- writer byte identical: {rt['writer_byte_identical']}", f"- nominal morph byte identical: {_v(rt['nominal_morph_byte_identical'])}"]
    c = r.get("nominal_check")
    if c:
        q = c["quality"]
        L += [
            "",
            "## Nominal check",
            "",
            f"- status {c['status']} ({_v(c['code'])}); parameter max error {_v(c['param_max_err_mm'])} mm ({c['param_unmeasured']} unmeasured of {c['param_items']}); boundary deviation {_v(c['deviation_max_mm'])} mm",
            f"- quality: min stretch {q['min_stretch']} (baseline {q['baseline_min_stretch']}), max aspect {q['max_aspect']} (baseline {q['baseline_max_aspect']}), "
            f"min edge {q['min_edge_mm']} mm (baseline {q['baseline_min_edge_mm']}), edge ratio {q['edge_ratio']}, dt ratio {q['dt_ratio']}, inverted {q['inverted']}, baseline_status {q['baseline_status']}",
            f"- interference {c['interference']}, tie {c['tie']}, warnings {', '.join(c['warnings']) or '-'}",
        ]
    en = r.get("envelope")
    if en:
        L += ["", "## Short envelope", "", f"- steps {en['steps_pct']} % (position parameters {en.get('pos_steps_mm')} mm), {en['steps_run']} run, {en['steps_failed']} failed", ""]
        L += ["| param | unit | last OK + | last OK - | first fail + | first fail - | limit + | limit - |", "|---|---|---|---|---|---|---|---|"]
        for p in en["params"]:
            u = p["unit"]
            ff = {d: "-" if p["first_fail"][d] is None else f"{p['first_fail'][d]} {u} {p['first_fail_code'][d]}" for d in ("+", "-")}
            L.append(f"| {p['param']} | {u} | {p['last_ok']['+']} {u} | {p['last_ok']['-']} {u} | {ff['+']} | {ff['-']} | {_v(p['limit_metric']['+'])} | {_v(p['limit_metric']['-'])} |")
    return "\n".join(L) + "\n"
