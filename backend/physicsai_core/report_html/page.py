"""HTML 보고서 공통 틀(upload-report.md §9.2·§9.3): 이스케이프·표·카드·inline SVG 그래프·크기 예산·단일 파일 조립.

외부 자원 0: CSS·그림(inline SVG)·PNG(`data:image/png;base64`)·데이터(inline JSON)·소량 JS(테마 전환)를 한 파일에 넣는다.
모든 사용자 문자열은 `esc`로 이스케이프한다. SVG 색은 CSS 클래스로(연속 색지도만 `#rrggbb` 속성). 같은 입력·같은 시각이면 같은 바이트.
"""

from __future__ import annotations

import base64
import html as _html
import json
import math
import os
import re
from dataclasses import dataclass, field
from string import Template
from typing import Any, Callable, Iterable, Sequence

from ..errors import DomainError

# upload-report.md §9.4 응답 헤더·HTML 메타와 같은 값(esl `html_report.REPORT_CSP`)
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
VIRIDIS = ("#440154", "#472d7b", "#3b528b", "#2c728e", "#21918c", "#28ae80", "#5ec962", "#addc30", "#fde725")


# ---- 한도·예산 ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Limits:
    """설정 `report.*`(upload-report.md §9.5)의 코드 기본값. 설정 클래스가 있으면 `limits_from`이 그 값을 쓴다."""

    max_bytes: int = 30 * 1024 * 1024
    max_images: int = 24
    max_image_bytes: int = 2 * 1024 * 1024
    max_table_rows: int = 500


def limits_from(settings: Any) -> Limits:
    """`settings.report`(ReportCfg)가 있으면 그 값, 없으면 코드 기본값(병합 전 단독 동작)."""
    cfg = getattr(settings, "report", None)
    if cfg is None:
        return Limits()
    d = Limits()
    return Limits(*(int(getattr(cfg, f, getattr(d, f))) for f in ("max_bytes", "max_images", "max_image_bytes", "max_table_rows")))


@dataclass(frozen=True)
class Budget:
    """크기 초과 시 단계적으로 줄이는 값(그림부터 — §9.4): 이미지 포함 여부·SVG 점 배율·표 행 배율."""

    images: bool = True
    svg_scale: float = 1.0
    row_scale: float = 1.0


BUDGETS = (Budget(), Budget(images=False), Budget(images=False, svg_scale=0.25, row_scale=0.2),
           Budget(images=False, svg_scale=0.05, row_scale=0.02))


@dataclass
class Ctx:
    limits: Limits
    budget: Budget
    generated_at: str
    platform_version: str
    images_used: int = 0
    images_omitted: int = 0
    truncated: list[str] = field(default_factory=list)

    def rows(self, n: int | None = None) -> int:
        cap = self.limits.max_table_rows if n is None else min(n, self.limits.max_table_rows)
        return max(1, int(cap * self.budget.row_scale))

    def pts(self, n: int) -> int:
        """SVG 한 그래프의 점 수 상한."""
        return max(10, int(n * self.budget.svg_scale))

    def cap_rows(self, rows: Sequence[Any], what: str, n: int | None = None) -> tuple[list[Any], str]:
        cap = self.rows(n)
        if len(rows) <= cap:
            return list(rows), ""
        self.truncated.append(what)
        return list(rows[:cap]), (f'<p class="muted small">{esc(what)} 앞 {cap}행만 표시합니다(전체 {len(rows)}행) — '
                                  "전체는 화면의 CSV 받기를 쓰세요.</p>")

    def image(self, path: str | None, alt: str) -> str:
        """기존 PNG 파일 → `<figure><img src="data:image/png;base64,…">`. 상한 초과·없음·PNG 아님은 생략 문구(개수만 센다)."""
        if not path:
            return ""
        ok = self.budget.images and self.images_used < self.limits.max_images
        data = _read_png(path, self.limits.max_image_bytes) if ok else None
        if data is None:
            self.images_omitted += 1
            return f'<p class="muted small">그림 생략: {esc(alt)}</p>'
        self.images_used += 1
        b64 = base64.b64encode(data).decode("ascii")
        return (f'<figure class="shot"><img alt="{esc(alt)}" src="data:image/png;base64,{b64}">'
                f"<figcaption>{esc(alt)}</figcaption></figure>")


def _read_png(path: str, max_bytes: int) -> bytes | None:
    try:
        if os.path.getsize(path) > max_bytes:
            return None
        with open(path, "rb") as fh:
            data = fh.read(max_bytes + 1)
    except OSError:
        return None
    return data if len(data) <= max_bytes and data.startswith(PNG_MAGIC) else None


# ---- 텍스트·숫자 ------------------------------------------------------------------------------------------


def esc(s: Any) -> str:
    return _html.escape("" if s is None else str(s), quote=True)


def finite(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def fmt(v: Any, digits: int = 4) -> str:
    """숫자 표시(이스케이프 포함): None → —, 비유한 → —/∞, 정수 그대로, 실수 유효숫자 digits."""
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return esc(v)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return esc(v)
    if math.isnan(f):
        return "—"
    if math.isinf(f):
        return "∞" if f > 0 else "−∞"
    if f == 0:
        return "0"
    a = abs(f)
    s = f"{f:.{digits}g}" if 1e-3 <= a < 1e6 else f"{f:.{max(digits - 1, 1)}e}"
    return s.replace("-", "−")


def pct(v: Any, digits: int = 3) -> str:
    return "—" if not finite(v) else f"{fmt(v, digits)}%"


class Raw(str):
    """표·kv에서 이스케이프하지 않을 HTML 조각."""


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]], num: Sequence[int] = (), cls: str = "") -> str:
    """표. num = 오른쪽 정렬 열. 문자열은 이스케이프, 숫자는 `fmt`, `Raw`는 그대로."""
    nums = set(num)
    h = "".join(f'<th class="num">{esc(x)}</th>' if i in nums else f"<th>{esc(x)}</th>" for i, x in enumerate(headers))
    body = []
    for r in rows:
        cells = []
        for i, v in enumerate(r):
            txt = v if isinstance(v, Raw) else (esc(v) if isinstance(v, str) else fmt(v))
            cells.append(f'<td class="num">{txt}</td>' if i in nums else f"<td>{txt}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="tw"><table class="{esc(cls)}"><thead><tr>{h}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def kv_table(pairs: Iterable[tuple[str, Any]]) -> str:
    rows = []
    for k, v in pairs:
        val = v if isinstance(v, Raw) else (esc(v) if isinstance(v, str) else fmt(v))
        rows.append(f"<tr><th>{esc(k)}</th><td>{val}</td></tr>")
    return f'<div class="tw"><table class="kv"><tbody>{"".join(rows)}</tbody></table></div>'


def cards(items: Iterable[tuple[str, Any]]) -> str:
    out = []
    for k, v in items:
        val = v if isinstance(v, Raw) else (esc(v) if isinstance(v, str) else fmt(v))
        out.append(f'<div class="card"><div class="k">{esc(k)}</div><div class="v">{val}</div></div>')
    return '<div class="cards">' + "".join(out) + "</div>"


def badge(text: str, kind: str = "na") -> str:
    return f'<span class="badge {esc(kind)}">{esc(text)}</span>'


def note(text: str, warn: bool = False) -> str:
    return f'<div class="note{" warn" if warn else ""}">{esc(text)}</div>'


def details(summary: str, inner: str) -> str:
    return f"<details><summary>{esc(summary)}</summary>{inner}</details>"


def section(id_: str, title: str, inner: str) -> str:
    return f'<section id="{esc(id_)}"><h2>{esc(title)}</h2>\n{inner}\n</section>'


def empty(text: str = "자료 없음") -> str:
    return f'<p class="muted">{esc(text)}</p>'


# ---- 연속 색 ----------------------------------------------------------------------------------------------


def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def viridis(t: float) -> str:
    x = min(1.0, max(0.0, t)) if math.isfinite(t) else 0.0
    f = x * (len(VIRIDIS) - 1)
    i = min(len(VIRIDIS) - 2, int(f))
    u = f - i
    a, b = _rgb(VIRIDIS[i]), _rgb(VIRIDIS[i + 1])
    return "#" + "".join(f"{round(min(255, max(0, a[k] + (b[k] - a[k]) * u))):02x}" for k in range(3))


# ---- SVG ------------------------------------------------------------------------------------------------


def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if not (finite(lo) and finite(hi)):
        return []
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / max(n, 1)
    p = 10.0 ** math.floor(math.log10(raw))
    step = next(m * p for m in (1, 2, 2.5, 5, 10) if m * p >= raw)
    t = math.ceil(lo / step - 1e-9) * step
    out: list[float] = []
    while t <= hi + step * 1e-9:
        out.append(0.0 if abs(t) < step * 1e-9 else round(t, 12))
        t += step
    return out


def _tick(v: float) -> str:
    return fmt(v, 3)


def _frame(lo: float, hi: float, pad: float = 0.05) -> tuple[float, float]:
    if hi <= lo:
        d = abs(lo) * 0.1 or 1.0
        return lo - d, hi + d
    d = (hi - lo) * pad
    return lo - d, hi + d


def _axes(x0: float, x1: float, y0: float, y1: float, L: int, T: int, pw: int, ph: int, xlabel: str, ylabel: str,
          width: int, height: int) -> tuple[Callable[[float], float], Callable[[float], float], list[str]]:
    X = lambda v: L + (v - x0) / ((x1 - x0) or 1.0) * pw  # noqa: E731
    Y = lambda v: T + ph - (v - y0) / ((y1 - y0) or 1.0) * ph  # noqa: E731
    out: list[str] = []
    for t in nice_ticks(y0, y1, 5):
        if y0 - 1e-12 <= t <= y1 + 1e-12:
            out.append(f'<line class="gr" x1="{L}" x2="{L + pw}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>'
                       f'<text x="{L - 4}" y="{Y(t) + 4:.1f}" text-anchor="end">{_tick(t)}</text>')
    for t in nice_ticks(x0, x1, max(3, pw // 90)):
        if x0 - 1e-12 <= t <= x1 + 1e-12:
            out.append(f'<text x="{X(t):.1f}" y="{T + ph + 14}" text-anchor="middle">{_tick(t)}</text>')
    out.append(f'<path class="ax" d="M{L},{T}V{T + ph}H{L + pw}"/>')
    out.append(f'<text x="{L + pw / 2:.0f}" y="{height - 6}" text-anchor="middle">{esc(xlabel)}</text>')
    out.append(f'<text x="12" y="{T + ph / 2:.0f}" text-anchor="middle" transform="rotate(-90 12 {T + ph / 2:.0f})">{esc(ylabel)}</text>')
    return X, Y, out


def _svg(width: int, height: int, label: str, parts: Sequence[str]) -> str:
    return f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(label)}">{"".join(parts)}</svg>'


def line_chart(series: Sequence[dict[str, Any]], *, xlabel: str = "", ylabel: str = "", title: str = "", width: int = 520,
               height: int = 260, markers: Sequence[dict[str, Any]] = (), max_points: int = 400,
               zero_base: bool = False) -> str:
    """꺾은선(여러 계열). series = [{x, y, cls('s1'..'s4'|'ln'|'ln-on'), label}], markers = [{x, y, label, cls}]."""
    sx: list[list[float]] = []
    sy: list[list[float]] = []
    for s in series:
        px = [(a, b) for a, b in zip(s["x"], s["y"]) if finite(a) and finite(b)]
        if len(px) > max_points:
            step = len(px) / max_points
            px = [px[int(i * step)] for i in range(max_points - 1)] + [px[-1]]
        sx.append([float(a) for a, _ in px])
        sy.append([float(b) for _, b in px])
    xs = [v for s in sx for v in s] + [m["x"] for m in markers if finite(m.get("x"))]
    ys = [v for s in sy for v in s] + [m["y"] for m in markers if finite(m.get("y"))]
    if not xs or not ys:
        return empty("그릴 자료 없음")
    x0, x1 = (min(xs), max(xs)) if max(xs) > min(xs) else _frame(min(xs), max(xs))
    y0, y1 = _frame(min(ys), max(ys)) if not zero_base else (min(0.0, min(ys)), max(ys) if max(ys) > min(0.0, min(ys)) else 1.0)
    L, R, T, B = 62, 12, 22 if title else 10, 40
    pw, ph = width - L - R, height - T - B
    X, Y, parts = _axes(x0, x1, y0, y1, L, T, pw, ph, xlabel, ylabel, width, height)
    if title:
        parts.insert(0, f'<text class="tl" x="{L}" y="14">{esc(title)}</text>')
    for s, a, b in zip(series, sx, sy):
        if a:
            d = "M" + "L".join(f"{X(p):.1f},{Y(q):.1f}" for p, q in zip(a, b))
            parts.append(f'<path class="{esc(s.get("cls", "s1"))}" d="{d}"><title>{esc(s.get("label", ""))}</title></path>')
    for m in markers:
        if finite(m.get("x")) and finite(m.get("y")):
            parts.append(f'<circle class="{esc(m.get("cls", "mk"))}" cx="{X(m["x"]):.1f}" cy="{Y(m["y"]):.1f}" r="3.5">'
                         f'<title>{esc(m.get("label", ""))}</title></circle>')
    return _svg(width, height, title or ylabel, parts)


def scatter_chart(points: Sequence[dict[str, Any]], *, xlabel: str = "", ylabel: str = "", title: str = "", width: int = 520,
                  height: int = 280, max_points: int = 2000, colorbar: tuple[float, float, str] | None = None,
                  vlines: Sequence[tuple[float, str]] = ()) -> str:
    """산점. points = [{x, y, cls('pt'|'pt2'|'ptb'), hollow, color('#rrggbb'), r, label}]. colorbar = (min, max, 라벨)."""
    pts = [p for p in points if finite(p.get("x")) and finite(p.get("y"))]
    if len(pts) > max_points:
        step = len(pts) / max_points
        pts = [pts[int(i * step)] for i in range(max_points)]
    if not pts:
        return empty("그릴 자료 없음")
    xs = [float(p["x"]) for p in pts]
    ys = [float(p["y"]) for p in pts]
    x0, x1 = _frame(min(xs), max(xs))
    y0, y1 = _frame(min(ys), max(ys))
    L, R, T, B = 62, 12 + (46 if colorbar else 0), 22 if title else 10, 40
    pw, ph = width - L - R, height - T - B
    X, Y, parts = _axes(x0, x1, y0, y1, L, T, pw, ph, xlabel, ylabel, width, height)
    if title:
        parts.insert(0, f'<text class="tl" x="{L}" y="14">{esc(title)}</text>')
    for p in pts:
        cls = esc(p.get("cls", "pt")) + (" hollow" if p.get("hollow") else "")
        col = p.get("color")
        fill = f' style="fill:{esc(col)}"' if col and not p.get("hollow") else ""  # CSS 클래스 규칙이 fill 속성을 이기므로 style로
        parts.append(f'<circle class="{cls}"{fill} cx="{X(p["x"]):.1f}" cy="{Y(p["y"]):.1f}" r="{p.get("r", 3.6)}">'
                     f'<title>{esc(p.get("label", ""))}</title></circle>')
    for v, lab in vlines:
        if finite(v):
            parts.append(f'<line class="vl" x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{T}" y2="{T + ph}"/>'
                         f'<text x="{X(v) + 3:.1f}" y="{T + 10}">{esc(lab)}</text>')
    if colorbar:
        lo, hi, lab = colorbar
        bx, bh = L + pw + 14, ph
        n = 24
        for i in range(n):
            t = 1 - (i + 0.5) / n
            parts.append(f'<rect fill="{viridis(t)}" x="{bx}" y="{T + i * bh / n:.1f}" width="10" height="{bh / n + 0.6:.1f}"/>')
        parts.append(f'<text x="{bx + 14}" y="{T + 8}">{_tick(hi)}</text><text x="{bx + 14}" y="{T + bh}">{_tick(lo)}</text>')
        parts.append(f'<text x="{bx}" y="{T - 2}">{esc(lab[:10])}</text>')
    return _svg(width, height, title or f"{ylabel} – {xlabel}", parts)


def bars_h(rows: Sequence[tuple[str, Sequence[tuple[float | None, str]]]], *, vmin: float = -1.0, vmax: float = 1.0,
           width: int = 520, title: str = "") -> str:
    """가로 막대(부호 있는 값, 0 기준선). rows = [(라벨, [(값|None, 클래스('bar'|'bar2'|'bar0')), …]), …]."""
    if not rows:
        return empty("그릴 자료 없음")
    per = max(len(r[1]) for r in rows)
    rh = 10 * per + 8
    L, R, T = 130, 40, 20 if title else 6
    pw = width - L - R
    height = T + rh * len(rows) + 24
    X = lambda v: L + (v - vmin) / ((vmax - vmin) or 1.0) * pw  # noqa: E731
    parts: list[str] = []
    if title:
        parts.append(f'<text class="tl" x="{L}" y="13">{esc(title)}</text>')
    for t in nice_ticks(vmin, vmax, 4):
        parts.append(f'<line class="gr" x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{T}" y2="{height - 22}"/>'
                     f'<text x="{X(t):.1f}" y="{height - 8}" text-anchor="middle">{_tick(t)}</text>')
    parts.append(f'<line class="ax" x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{T}" y2="{height - 22}"/>')
    for i, (lab, vals) in enumerate(rows):
        y = T + i * rh
        parts.append(f'<text x="{L - 6}" y="{y + rh / 2 + 3:.1f}" text-anchor="end">{esc(lab[:22])}</text>')
        for j, (v, cls) in enumerate(vals):
            if v is None or not finite(v):
                continue
            a, b = sorted((X(0), X(max(vmin, min(vmax, float(v))))))
            parts.append(f'<rect class="{esc(cls)}" x="{a:.1f}" y="{y + 4 + j * 10}" width="{max(b - a, 0.8):.1f}" height="8">'
                         f"<title>{esc(lab)}: {fmt(v, 4)}</title></rect>")
    return _svg(width, height, title or "막대 그래프", parts)


# ---- 문서 조립 --------------------------------------------------------------------------------------------

CSS = """
:root{--bg:#ffffff;--fg:#1c2230;--muted:#5d6676;--card:#f5f6f8;--border:#d8dce2;--accent:#2563c9;
--ok:#18794e;--ok-bg:#e3f4ea;--bad:#b42318;--bad-bg:#fde8e6;--warn:#8a5a00;--warn-bg:#fdf1d6;--grid:#e4e7eb;
--s1:#2563c9;--s2:#d9480f;--s3:#7a8291;--s4:#0f9d8a;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#13161b;--fg:#e4e7ec;--muted:#9aa3b2;
--card:#1c2027;--border:#343a45;--accent:#6ea2ff;--ok:#5ad19a;--ok-bg:#16352a;--bad:#ff8a7e;--bad-bg:#3d1c19;
--warn:#f0c060;--warn-bg:#3a2e12;--grid:#2a2f38;--s1:#6ea2ff;--s2:#ff9a5c;--s3:#a3abb8;--s4:#3fd2bd;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#13161b;--fg:#e4e7ec;--muted:#9aa3b2;--card:#1c2027;--border:#343a45;--accent:#6ea2ff;
--ok:#5ad19a;--ok-bg:#16352a;--bad:#ff8a7e;--bad-bg:#3d1c19;--warn:#f0c060;--warn-bg:#3a2e12;--grid:#2a2f38;
--s1:#6ea2ff;--s2:#ff9a5c;--s3:#a3abb8;--s4:#3fd2bd;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Segoe UI","Malgun Gothic","Apple SD Gothic Neo",sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px 16px 48px}
h1{font-size:22px;margin:8px 0 4px}h2{font-size:17px;margin:0 0 10px}h3{font-size:14px;margin:14px 0 6px}
p{margin:6px 0}.muted{color:var(--muted)}.small{font-size:12px}
section{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px 16px;margin:14px 0}
nav.toc{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;margin:8px 0}nav.toc a{color:var(--accent);text-decoration:none}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{border-bottom:1px solid var(--border);padding:4px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}td.num,th.num{text-align:right;white-space:nowrap}.tw{overflow-x:auto}
table.kv th{width:200px;white-space:nowrap}
.badge{display:inline-block;padding:1px 10px;border-radius:999px;font-weight:700;font-size:13px}
.pass{color:var(--ok);background:var(--ok-bg)}.fail{color:var(--bad);background:var(--bad-bg)}
.warnb{color:var(--warn);background:var(--warn-bg)}.na{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:8px 0}
.card{border:1px solid var(--border);border-radius:6px;padding:8px 10px;background:var(--bg)}
.card .k{font-size:12px;color:var(--muted)}.card .v{font-size:18px;font-weight:650;font-variant-numeric:tabular-nums}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
svg.chart{width:100%;max-width:620px;height:auto;display:block;font-size:11px}
svg .ax{stroke:var(--muted);stroke-width:1;fill:none}svg .gr{stroke:var(--grid);stroke-width:1}
svg text{fill:var(--muted)}svg .tl{fill:var(--fg)}
svg .s1{stroke:var(--s1);fill:none;stroke-width:1.8}svg .s2{stroke:var(--s2);fill:none;stroke-width:1.8}
svg .s3{stroke:var(--s3);fill:none;stroke-width:1.4;stroke-dasharray:4 3}svg .s4{stroke:var(--s4);fill:none;stroke-width:1.8}
svg .ln{stroke:var(--s3);fill:none;stroke-width:1;opacity:.45}svg .ln-on{stroke:var(--s2);fill:none;stroke-width:2.2}
svg .vl{stroke:var(--bad);stroke-width:1.2;stroke-dasharray:3 3}svg .mk{fill:var(--s2)}svg .mk1{fill:var(--bad)}
svg .pt{fill:var(--s1);opacity:.85}svg .pt2{fill:var(--s2);opacity:.9}svg .ptb{fill:var(--bad)}svg .ptg{fill:var(--s3);opacity:.7}
svg .hollow{fill:none;stroke:var(--s2);stroke-width:1.6}
svg .bar{fill:var(--s1)}svg .bar2{fill:var(--s2)}svg .bar0{fill:var(--s4)}
.note{border-left:3px solid var(--accent);padding:6px 10px;margin:8px 0;background:var(--bg)}.warn{border-left-color:var(--bad)}
figure.shot{margin:8px 0}figure.shot img{max-width:100%;height:auto;border:1px solid var(--border)}figcaption{font-size:12px;color:var(--muted)}
details{margin:6px 0}summary{cursor:pointer;color:var(--accent)}code{font-size:12px;word-break:break-all}
button.tg{font:inherit;font-size:12px;padding:2px 8px;border:1px solid var(--border);background:var(--bg);color:var(--fg);border-radius:4px;cursor:pointer}
@media print{button.tg,nav.toc{display:none}}
"""

THEME_JS = """(function(){var r=document.documentElement,b=document.getElementById('theme-btn');if(!b)return;
var m=['auto','light','dark'],i=0;b.onclick=function(){i=(i+1)%3;if(m[i]==='auto')r.removeAttribute('data-theme');
else r.setAttribute('data-theme',m[i]);b.textContent='테마: '+({auto:'자동',light:'라이트',dark:'다크'})[m[i]];};})();"""

PAGE = Template("""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="$csp">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="physicsai $version">
<meta name="referrer" content="no-referrer">
<title>$title</title>
<style>$css</style>
</head>
<body>
<main>
$body
</main>
<script type="application/json" id="pai-report-data">$data</script>
<script>$script</script>
</body>
</html>
""")

_SCRIPT_BREAK = re.compile(r"<(?=/|!--|script)", re.I)


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    return o


def json_text(obj: Any) -> str:
    """`<script type="application/json">` 본문용 JSON: `</`·`<!--`·`<script`의 `<`를 `\\u003c`로 바꿔 블록이 닫히지 않게."""
    txt = json.dumps(_clean(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False, sort_keys=True)
    return _SCRIPT_BREAK.sub(r"\\u003c", txt)


@dataclass
class Doc:
    """대상별 렌더러가 돌려주는 문서 내용."""

    title: str                              # 제목(예 "⑥ 최적화 결과 요약")
    meta: list[tuple[str, Any]]             # 머리 표(키, 값 — 이미 문자열이거나 Raw)
    sections: list[tuple[str, str, str]]    # (id, 제목, html)
    warnings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)  # inline JSON(작게)
    badge_html: str = ""                    # 제목 옆 표지(예 "HyperStudy(레거시)")


def assemble(doc: Doc, ctx: Ctx) -> str:
    """Doc → 단일 파일 HTML."""
    secs = list(doc.sections)
    warn = list(doc.warnings)
    if ctx.images_omitted:
        warn.append(f"그림 {ctx.images_omitted}장 생략(개수·크기 상한 report.max_images·max_image_bytes 또는 파일 크기 한도)")
    for what in ctx.truncated:
        warn.append(f"{what}은(는) 상한까지만 표시했습니다")
    warn_html = ("".join(note(w, True) for w in warn) if warn else empty("경고 없음"))
    secs.append(("warnings", "상태·경고", warn_html))
    foot = ("<p class=\"muted small\">이 파일은 외부 연결 없이 열립니다. 원천 id: "
            + (", ".join(f"<code>{esc(s)}</code>" for s in doc.sources) or "—") + "</p>")
    secs.append(("source", "원천", foot))
    toc = '<nav class="toc">' + "".join(f'<a href="#{esc(i)}">{esc(t)}</a>' for i, t, _ in secs) + "</nav>"
    head = (f'<header><h1>{esc(doc.title)} {doc.badge_html}</h1>{kv_table(doc.meta)}'
            f'<p><button class="tg" id="theme-btn" type="button">테마: 자동</button></p></header>')
    body = head + toc + "\n".join(section(i, t, h) for i, t, h in secs)
    data = {**doc.data, "generated_at": ctx.generated_at, "platform_version": ctx.platform_version}
    return PAGE.substitute(csp=esc(REPORT_CSP), version=esc(ctx.platform_version), title=esc(doc.title), css=CSS, body=body,
                           data=json_text(data), script=THEME_JS)


def render(build: Callable[[Ctx], Doc], limits: Limits, *, generated_at: str, platform_version: str) -> bytes:
    """예산을 줄여 가며(그림 → 점·행) `max_bytes` 이하 HTML을 만든다. 끝까지 넘으면 413 REPORT_TOO_LARGE."""
    size = 0
    for b in BUDGETS:
        ctx = Ctx(limits, b, generated_at, platform_version)
        out = assemble(build(ctx), ctx).encode("utf-8")
        size = len(out)
        if size <= limits.max_bytes:
            return out
    raise DomainError("REPORT_TOO_LARGE", f"보고서가 크기 상한({limits.max_bytes // (1024 * 1024)} MiB)을 넘습니다 — 선택 범위를 줄이세요",
                      status=413, size=size, limit=limits.max_bytes)
