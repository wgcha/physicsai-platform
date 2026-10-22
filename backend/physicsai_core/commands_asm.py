"""조립 매칭 명령 쌍 치환(asm-match.md §6.2 AM-10) — 관리자 설정 템플릿을 고치지 않고 인자 쌍을 바꿔 끼운다.

방식 M(조립 매칭 세트)의 `paicad_*` 호출은 값에 `asm_match`(확정본 asm_match.json 경로)가 있으면 템플릿을 아래 규칙으로 바꾼다
(`commands_render.render_argv`가 호출 — 값 검사·경로 표기는 같은 경로):

| 기존 쌍 | 방식 M |
|---|---|
| `--renum-csv {renum_csv}` | `--asm-match {asm_match}` |
| `--baseline-inc {baseline_inc}` | 이미 `--assem-dir`이 있으면 삭제, 없으면 `--assem-dir {assem_dir}` |
| `--out-inc {out_inc}` | `--out-patch {out_patch}` |
| `--inc {cushion_inc}`(cushion write) | `--patch {node_patch}`(값이 없으면 삭제 — 공칭) |
| (끝) | `--asm-match` 가 없으면 추가(morph), `--cache-dir {asm_cache_dir}` 추가 |

`paicad_asm_parts`는 ④ 경로(`features_json` 없음·`cad_input` 있음)에서 `--features` 쌍을 `--cad {cad_input}`으로 바꾼다.
기존 방식 L(값에 `asm_match` 없음)은 템플릿을 그대로 쓴다 — 기존 argv 불변.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

# 방식 M 쌍 치환 대상 키(tag·morph·check·run·cushion write·뷰 미리보기). extract는 RENUM 대응 검사가 선택이라 대상이 아니다.
ASM_PAIR_KEYS = frozenset({"paicad_tag", "paicad_morph", "paicad_check", "paicad_run", "paicad_cushion_write", "paicad_view_preview"})
# 치환 결과에 새로 나올 수 있는 placeholder(허용 목록에 더한다)
ASM_EXTRA_PLACEHOLDERS = frozenset({"asm_match", "asm_cache_dir", "out_patch", "node_patch", "assem_dir"})


def is_matched(key: str, values: Mapping[str, str]) -> bool:
    """이 호출이 방식 M인가(값에 `asm_match`가 있음)."""
    return key in ASM_PAIR_KEYS and bool(values.get("asm_match"))


def expand(key: str, template: Sequence[str], values: Mapping[str, str]) -> list[str]:
    """템플릿 → 호출용 템플릿(방식 M·asm_parts ④ 치환). 해당 없으면 사본 그대로."""
    tpl = list(template)
    if key == "paicad_asm_parts" and not values.get("features_json") and values.get("cad_input"):
        return _swap(tpl, "--features", "{features_json}", "--cad", "{cad_input}")
    if not is_matched(key, values):
        return tpl
    has_assem = "--assem-dir" in tpl
    out: list[str] = []
    i = 0
    while i < len(tpl):
        el, nxt = tpl[i], (tpl[i + 1] if i + 1 < len(tpl) else None)
        if el == "--renum-csv" and nxt == "{renum_csv}":
            out += ["--asm-match", "{asm_match}"]
        elif el == "--baseline-inc" and nxt == "{baseline_inc}":
            if not has_assem:
                out += ["--assem-dir", "{assem_dir}"]
                has_assem = True
        elif el == "--out-inc" and nxt == "{out_inc}":
            out += ["--out-patch", "{out_patch}"]
        elif el == "--inc" and nxt == "{cushion_inc}":
            if values.get("node_patch"):
                out += ["--patch", "{node_patch}"]
        else:
            out.append(el)
            i += 1
            continue
        i += 2
    if "--asm-match" not in out:
        out += ["--asm-match", "{asm_match}"]
    if "--assem-dir" not in out:
        out += ["--assem-dir", "{assem_dir}"]
    if "--cache-dir" not in out:
        out += ["--cache-dir", "{asm_cache_dir}"]
    return out


def _swap(tpl: list[str], flag: str, ph: str, new_flag: str, new_ph: str) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tpl):
        if tpl[i] == flag and i + 1 < len(tpl) and tpl[i + 1] == ph:
            out += [new_flag, new_ph]
            i += 2
        else:
            out.append(tpl[i])
            i += 1
    return out
