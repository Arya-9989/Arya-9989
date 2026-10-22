#!/usr/bin/env python3
"""Build the profile README and its self-hosted SVG artwork.

Every SVG comes in a light and a dark variant. The README picks the variant with
<picture><source media="(prefers-color-scheme: dark)">, which GitHub's
<themed-picture> element also maps onto the viewer's GitHub theme.

Responsive strategy (GitHub strips CSS from README HTML):
  * Tiles have fixed widths (280 or 420 units) and sit inline in one paragraph,
    so they flow 3-up / 2-up on desktop (846px README column) and stack on
    mobile. 280 tiles are never scaled down on phones.
  * Full-width pieces (hero, headlines) and 420 tiles carry a second layout
    inside the SVG, switched by an @media rule on the rendered image width.
  * Media queries that combine width with prefers-color-scheme are not used:
    <themed-picture> rewrites any source mentioning the colour scheme.

Text is wrapped here, measured with Chromium canvas against Segoe UI and Arial
(the widest common fallbacks), plus a safety margin for SF Pro, Inter and DejaVu.

Usage:  python scripts/build_profile.py      (needs `pip install playwright`)
Then:   svgo --config scripts/svgo.config.mjs -q -f assets
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# ---------------------------------------------------------------- type & colour
DISPLAY = ("-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI Variable Display', "
           "'Segoe UI', Inter, Roboto, 'Helvetica Neue', Helvetica, Arial, Arimo, 'Liberation Sans', 'Nimbus Sans', sans-serif")
TEXT = ("-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI Variable Text', "
        "'Segoe UI', Inter, Roboto, 'Helvetica Neue', Helvetica, Arial, Arimo, 'Liberation Sans', 'Nimbus Sans', sans-serif")
MONO = "ui-monospace, 'SF Mono', 'Cascadia Code', Consolas, Menlo, 'Liberation Mono', monospace"

THEMES = {
    "light": dict(fg="#1d1d1f", fg2="#6e6e73", tile="#f5f5f7", tile_op="1", stroke="none",
                  hero="#f5f5f7", hair="#d2d2d7", link="#0066cc", fill="#0071e3",
                  grad=("#0066cc", "#0b7a96"), on_fill="#ffffff", page="#ffffff"),
    "dark": dict(fg="#f5f5f7", fg2="#a1a1a6", tile="#ffffff", tile_op="0.06", stroke="#ffffff",
                 hero="#000000", hair="#3a3a3c", link="#2997ff", fill="#0071e3",
                 grad=("#5ab4ff", "#5fd4e2"), on_fill="#ffffff", page="#0d1117"),
}

# Per-repo identity accents (light, dark): used only in the motif and eyebrow.
REPO_ACCENT = {
    "autoswe": ("#5e5ce6", "#8a87ff"),
    "securecart": ("#0040dd", "#5b9dff"),
    "microservices": ("#086f8c", "#3fd0ea"),
    "multitenant": ("#0f766e", "#3dd6c1"),
    "momentum": ("#1d7a34", "#30d158"),
    "more": (None, None),
}


def tracking(size: float) -> float:
    """Apple-style tracking: tight for display sizes, neutral for text."""
    if size >= 60:
        em = -0.02
    elif size >= 40:
        em = -0.012
    elif size >= 24:
        em = -0.006
    elif size >= 17:
        em = -0.002
    else:
        em = 0.0
    return round(size * em, 3)


# ---------------------------------------------------------------- measurement
class Measurer:
    # Widths are the max of Segoe UI and Arial times a safety factor:
    #   body text  x1.08 covers SF Pro, Inter and Noto Sans (measured up to +7.7%);
    #   display    x1.24 also covers DejaVu Sans Bold (measured up to +23%), so large
    #              type never clips on minimal Linux installs.
    SAFETY = 1.08
    DISPLAY_SAFETY = 1.24

    def __init__(self, page):
        self.page = page
        self.cache: dict[tuple, float] = {}
        page.set_content("<canvas id=c></canvas>")

    def width(self, text: str, size: float, weight: int = 400, mono: bool = False, display: bool = False) -> float:
        key = (text, size, weight, mono, display)
        if key not in self.cache:
            fams = ["Consolas", "Courier New"] if mono else ["Segoe UI", "Arial"]
            ws = self.page.evaluate(
                """([t, s, w, fams, ls]) => { const c = document.getElementById('c').getContext('2d');
                     return fams.map(f => { c.font = `${w} ${s}px "${f}"`; c.letterSpacing = ls + 'px';
                                             return c.measureText(t).width; }); }""",
                [text, size, weight, fams, tracking(size)])
            self.cache[key] = max(ws) * (self.DISPLAY_SAFETY if display else self.SAFETY)
        return self.cache[key]


M: Measurer  # set in main()

NB = " "


def tokens_for(text: str, list_mode: bool) -> list[str]:
    if list_mode and " · " in text:
        items = text.split(" · ")
        return [it.replace(" ", NB) + (NB + "·" if i < len(items) - 1 else "") for i, it in enumerate(items)]
    return text.split(" ")


def parse_rich(text: str) -> list[tuple[str, bool]]:
    """'plain **bold** plain' -> [(word, bold), ...] (words keep no spaces)."""
    out = []
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        for w in part.split():
            out.append((w, i % 2 == 1))
    return out


def wrap(text: str, size: float, maxw: float, weight: int = 400, list_mode: bool = False,
         bold_weight: int = 600, display: bool = False, slack: float = 0) -> list[list[tuple[str, bool]]]:
    """Greedy wrap. Returns lines of (word, bold) runs.

    A line fits when common faces (x1.08) fit `maxw`; for display/bold text the widest
    fallback (x1.24) must also fit `maxw + slack` (slack = padding it may spill into)."""
    words = parse_rich(text) if "**" in text else [(t, False) for t in tokens_for(text, list_mode)]
    lines, cur = [], []

    def w_of(line, disp=False):
        s = " ".join(x for x, _ in line).replace(NB, " ")
        # measure bold words separately for accuracy
        total = 0.0
        for j, (x, b) in enumerate(line):
            last = j == len(line) - 1
            if last and x.endswith(NB + "·"):
                x = x[:-2]
            seg = x.replace(NB, " ") + ("" if last else " ")
            total += M.width(seg, size, bold_weight if b else weight, display=disp)
        return total if line else 0.0

    def fits(line):
        return w_of(line) <= maxw and (not display or w_of(line, True) <= maxw + slack)

    # a list item longer than the line may break between its own words
    expanded = []
    for wd in words:
        if NB in wd[0] and not fits([wd]):
            parts = wd[0].split(NB)
            if parts[-1] == "·":
                parts = parts[:-2] + [parts[-2] + NB + "·"]
            expanded += [(x, wd[1]) for x in parts]
        else:
            expanded.append(wd)
    words = expanded
    # Balanced wrap: fewest lines first, then the least raggedness (squared slack;
    # the last line counts half), so short items are not stranded on their own line.
    n = len(words)
    INF = float("inf")
    best = [(0.0, n)] * (n + 1)
    best[n] = (0.0, n)
    for i in range(n - 1, -1, -1):
        cand = (INF, n)
        for j in range(i + 1, n + 1):
            ln = words[i:j]
            if j > i + 1 and not fits(ln):
                break
            slack_ = max(0.0, maxw - w_of(ln))
            cost = maxw * maxw * 4 + (slack_ * slack_) * (0.5 if j == n else 1.0) + best[j][0]
            if cost < cand[0]:
                cand = (cost, j)
        best[i] = cand
    i = 0
    while i < n:
        j = best[i][1]
        lines.append(words[i:j])
        i = j
    # drop a dangling list separator at the end of a line
    cleaned = []
    for ln in lines:
        x, b = ln[-1]
        if x.endswith(NB + "·"):
            ln = ln[:-1] + [(x[: -2], b)]
        cleaned.append(ln)
    for ln in cleaned:
        assert fits(ln) or len(ln) == 1, f"overflow: {ln}"
    return cleaned


# ---------------------------------------------------------------- SVG helpers
def esc(s: str) -> str:
    return html.escape(s.replace(NB, " "), quote=True)


def line_svg(runs, x, y, size, weight, fill, fam="t", bold_fill=None, anchor=None, extra="", bold_weight=600, cls=""):
    ls = tracking(size)
    attrs = f'x="{x:g}" y="{y:g}" class="{(fam + " " + cls).strip()}" font-size="{size:g}" font-weight="{weight}" fill="{fill}"'
    if ls:
        attrs += f' letter-spacing="{ls:g}"'
    if anchor:
        attrs += f' text-anchor="{anchor}"'
    if extra:
        attrs += " " + extra
    if isinstance(runs, str):
        return f"<text {attrs}>{esc(runs)}</text>"
    parts = []
    for j, (w, b) in enumerate(runs):
        s = esc(w) + (" " if j < len(runs) - 1 else "")
        if b:
            parts.append(f'<tspan font-weight="{bold_weight}" fill="{bold_fill or fill}">{s}</tspan>')
        else:
            parts.append(s)
    # merge adjacent plain parts
    return f"<text {attrs}>{''.join(parts)}</text>"


def plain(lines) -> str:
    return " ".join(" ".join(w for w, _ in ln) for ln in lines).replace(NB, " ")


def svg_doc(w, h, title, body, style="", ident="t"):
    css = (f".d{{font-family:{DISPLAY}}}.t{{font-family:{TEXT}}}.m{{font-family:{MONO}}}" + style)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:g}" height="{h:g}" viewBox="0 0 {w:g} {h:g}" '
            f'role="img" aria-labelledby="{ident}">'
            f'<title id="{ident}">{esc(title)}</title><style>{css}</style>{body}</svg>\n')


def cap(size):  # approximate cap height of the system faces
    return size * 0.71


# ---------------------------------------------------------------- text stack layout
@dataclass
class Block:
    text: str
    size: float
    lh: float
    weight: int = 400
    color: str = "fg"          # theme key or literal colour
    gap: float = 0             # space above this block (baseline-to-cap aware)
    fam: str = "t"
    list_mode: bool = False
    bold_color: str = "fg"
    maxw: float | None = None  # override wrap width
    nowrap: bool = False


def layout_blocks(blocks: list[Block], x: float, top: float, maxw: float, th: dict, slack: float = 0):
    """Stack blocks from `top`. Returns (svg, bottom_y, plain_texts)."""
    out, y, texts = [], top, []
    first = True
    for bl in blocks:
        disp = bl.fam == "d" or (bl.weight >= 600 and bl.size >= 17)
        if bl.nowrap:
            while (M.width(bl.text, bl.size, bl.weight) > (bl.maxw or maxw)
                   or M.width(bl.text, bl.size, bl.weight, display=True) > (bl.maxw or maxw) + slack):
                bl = Block(**{**bl.__dict__, "size": round(bl.size - 1, 1)})
            lines = [[(bl.text, False)]]
        else:
            lines = wrap(bl.text, bl.size, bl.maxw or maxw, bl.weight, bl.list_mode, display=disp, slack=slack)
        col = th.get(bl.color, bl.color)
        bcol = th.get(bl.bold_color, bl.bold_color)
        y += (0 if first else bl.gap)
        base = y + cap(bl.size)
        for i, ln in enumerate(lines):
            out.append(line_svg(ln, x, round(base + i * bl.lh, 1), bl.size, bl.weight, col, bl.fam, bcol))
        y = base + (len(lines) - 1) * bl.lh + bl.size * 0.24  # descender allowance
        texts.append(plain(lines))
        first = False
    return "".join(out), y, texts


# ---------------------------------------------------------------- motifs
def motif(kind: str, x: float, y: float, accent: str, th: dict) -> str:
    """Small line-art identity glyph in a 64x36 box with top-left (x, y)."""
    s = f'stroke="{accent}" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"'
    if kind == "autoswe":  # five-agent pipeline
        dots = "".join(f'<circle cx="{x + 4 + i * 14:g}" cy="{y + 18:g}" r="4" '
                       + (f'fill="{accent}"/>' if i == 4 else f'{s}/>') for i in range(5))
        return f'<path d="M{x + 8:g} {y + 18:g}H{x + 56:g}" {s} opacity=".45"/>{dots}'
    if kind == "securecart":  # bag with keyhole
        return (f'<path d="M{x + 18:g} {y + 12:g}h28l2 22H{x + 16:g}z" {s}/>'
                f'<path d="M{x + 25:g} {y + 12:g}v-2a7 7 0 0 1 14 0v2" {s}/>'
                f'<circle cx="{x + 32:g}" cy="{y + 21:g}" r="2.6" fill="{accent}"/>'
                f'<path d="M{x + 32:g} {y + 23:g}v5" {s}/>')
    if kind == "microservices":  # gateway fanning out to services
        g = (f'<rect x="{x + 2:g}" y="{y + 11:g}" width="14" height="14" rx="4" fill="{accent}"/>')
        lines = "".join(f'<path d="M{x + 16:g} {y + 18:g}C{x + 30:g} {y + 18:g} {x + 30:g} {y + 4 + i * 14:g} {x + 44:g} {y + 4 + i * 14:g}" {s} opacity=".55"/>' for i in range(3))
        nodes = "".join(f'<circle cx="{x + 50:g}" cy="{y + 4 + i * 14:g}" r="4.5" {s}/>' for i in range(3))
        return g + lines + nodes
    if kind == "multitenant":  # sealed, separate spaces
        return "".join(f'<rect x="{x + 1 + i * 22:g}" y="{y + 8:g}" width="18" height="20" rx="5" '
                       + (f'fill="{accent}"/>' if i == 1 else f'{s}/>') for i in range(3))
    if kind == "momentum":  # price sparkline
        pts = [(0, 28), (9, 22), (17, 25), (26, 15), (35, 18), (44, 9), (53, 12), (62, 4)]
        d = "M" + " L".join(f"{x + px:g} {y + py:g}" for px, py in pts)
        return f'<path d="{d}" {s}/><circle cx="{x + 62:g}" cy="{y + 4:g}" r="3.2" fill="{accent}"/>'
    if kind == "more":
        c = th["fg2"]
        st = f'stroke="{c}" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"'
        return (f'<circle cx="{x + 46:g}" cy="{y + 18:g}" r="17" {st}/>'
                f'<path d="M{x + 40:g} {y + 24:g}L{x + 52:g} {y + 12:g}M{x + 43.5:g} {y + 12:g}H{x + 52:g}V{y + 20.5:g}" {st}/>')
    return ""


# ---------------------------------------------------------------- components
REDUCED = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"


def hero(theme: str):
    th = THEMES[theme]
    W, PANEL_X = 846, 9
    X = 64
    maxw = W - 2 * X
    eyebrow = "DevOps Engineer · Cloud · Security"
    name = "Arya Mahindrakar"
    statement = "I build, ship and secure cloud applications."
    meta_w = "AWS Certified Cloud Practitioner  ·  Pune, India"
    status = "Open to work"
    stages = ["build", "test", "scan", "deploy"]

    # ---- wide layout, anchored to the bottom of the panel
    H = 452
    b_meta = H - 58
    b_state = b_meta - 46
    b_name = b_state - 52
    b_eye = b_name - 84
    # largest name size (<= 80) that stays inside the panel even in the widest fallback face
    name_sz = next(z for z in range(80, 56, -1) if M.width(name, z, 600, display=True) <= (W - PANEL_X - 8) - (X - 3))
    room = (W - PANEL_X - 24) - X
    st_sz = next(z for z in range(30, 22, -1) if M.width(statement, z, 600, display=True) <= room)
    assert M.width(eyebrow, 21, 600, display=True) <= maxw
    assert M.width(meta_w, 16, 400) <= maxw
    sw = M.width(statement, st_sz, 600) / Measurer.SAFETY
    wide = [
        line_svg(eyebrow, X, b_eye, 21, 600, th["fg2"], "d", cls='r r1'),
        line_svg(name, X - 3, b_name, name_sz, 600, th["fg"], "d", cls='r r2'),
        line_svg(statement, X, b_state, st_sz, 600, "url(#gw)", "d", cls='r r3'),
        line_svg(meta_w, X, b_meta, 16, 400, th["fg2"], "t", cls='r r4'),
    ]
    # pipeline motif (top-left) and availability (top-right)
    py, step = 86, 128
    px = [X + 6 + i * step for i in range(4)]
    pipe = [f'<path d="M{px[0]:g} {py}H{px[-1]:g}" stroke="{th["hair"]}" stroke-width="2" stroke-linecap="round"/>',
            f'<path class="flow" d="M{px[0]:g} {py}H{px[-1]:g}" stroke="{th["fill"] if theme == "light" else th["link"]}" '
            f'stroke-width="2" stroke-linecap="round" pathLength="1" stroke-dasharray="1" fill="none"/>']
    for i, (cx, lab) in enumerate(zip(px, stages)):
        acc = th["fill"] if theme == "light" else th["link"]
        pipe.append(f'<g class="node n{i}"><circle cx="{cx:g}" cy="{py}" r="9" fill="{acc}"/>'
                    f'<path d="M{cx - 4:g} {py + 0.2:g}l2.6 2.6 5-5.2" stroke="{th["hero"] if theme == "dark" else "#fff"}" '
                    f'stroke-width="1.9" fill="none" stroke-linecap="round" stroke-linejoin="round"/></g>')
        pipe.append(line_svg(lab, cx, py + 32, 13, 400, th["fg2"], "m", anchor="middle"))
    st_w = M.width(status, 15, 500) / Measurer.SAFETY
    sx = W - X - st_w
    green = "#248a3d" if theme == "light" else "#30d158"
    avail = (f'<circle class="halo" cx="{sx - 14:g}" cy="{py - 5:g}" r="4" fill="{green}"/>'
             f'<circle cx="{sx - 14:g}" cy="{py - 5:g}" r="4" fill="{green}"/>'
             + line_svg(status, sx, py, 15, 500, th["fg"], "t"))
    wide_svg = f'<g class="w">{"".join(pipe)}{avail}{"".join(wide)}</g>'

    # ---- narrow layout (rendered width <= 640px): bigger relative type, top-anchored
    k = 846 / 308  # units per CSS px at a 390px phone
    n_eye, n_name, n_state, n_meta = 12.5 * k, 31 * k, 15 * k, 11.5 * k
    nx = 20 * k
    nmax = W - 2 * nx
    st_lines = wrap(statement, n_state, nmax, 600, display=True)
    meta_lines = ["AWS Certified Cloud Practitioner", "Pune, India  ·  Open to work"]
    while M.width(name, n_name, 600, display=True) > (W - PANEL_X - 8) - (nx - 4):
        n_name -= 1
    assert M.width(eyebrow, n_eye, 600, display=True) <= nmax
    y = 26 * k + cap(n_eye)
    narrow = [line_svg(eyebrow, nx, round(y, 1), round(n_eye, 1), 600, th["fg2"], "d")]
    y += 13 * k + cap(n_name)
    narrow.append(line_svg(name, nx - 4, round(y, 1), round(n_name, 1), 600, th["fg"], "d"))
    y += 11 * k + cap(n_state)
    ng_y0 = y
    for i, ln in enumerate(st_lines):
        narrow.append(line_svg(ln, nx, round(y + i * 19.5 * k, 1), round(n_state, 1), 600, "url(#gn)", "d"))
    y += (len(st_lines) - 1) * 19.5 * k + 14 * k + cap(n_meta)
    for i, ml in enumerate(meta_lines):
        narrow.append(line_svg(ml, nx, round(y + i * 16 * k, 1), round(n_meta, 1), 400, th["fg2"], "t"))
    n_bottom = y + 16 * k + 14 * k
    H = max(H, round(n_bottom))
    nsw = max(M.width(plain([ln]), n_state, 600) for ln in st_lines) / Measurer.SAFETY
    narrow_svg = f'<g class="n">{"".join(narrow)}</g>'

    g0, g1 = th["grad"]
    defs = (f'<defs><linearGradient id="gw" gradientUnits="userSpaceOnUse" x1="{X:g}" y1="0" x2="{X + sw:g}" y2="0">'
            f'<stop offset="0" stop-color="{g0}"/><stop offset="1" stop-color="{g1}"/></linearGradient>'
            f'<linearGradient id="gn" gradientUnits="userSpaceOnUse" x1="{nx:g}" y1="0" x2="{nx + nsw:g}" y2="0">'
            f'<stop offset="0" stop-color="{g0}"/><stop offset="1" stop-color="{g1}"/></linearGradient></defs>')
    ease = "cubic-bezier(0.4,0,0.6,1)"
    style = (
        f".n{{display:none}}@media (max-width:640px){{.w{{display:none}}.n{{display:inline}}.panel{{rx:46px;ry:46px}}}}"
        f"@keyframes rise{{from{{opacity:0;transform:translateY(14px)}}to{{opacity:1;transform:none}}}}"
        f".r{{animation:rise .7s {ease} both}}.r1{{animation-delay:.05s}}.r2{{animation-delay:.12s}}"
        f".r3{{animation-delay:.2s}}.r4{{animation-delay:.28s}}"
        f"@keyframes flow{{from{{stroke-dashoffset:1}}to{{stroke-dashoffset:0}}}}"
        f".flow{{animation:flow 1.6s {ease} .5s both}}"
        f"@keyframes pop{{from{{opacity:0;transform:scale(.6)}}to{{opacity:1;transform:none}}}}"
        f".node{{transform-box:fill-box;transform-origin:center;animation:pop .32s {ease} both}}"
        + "".join(f".n{i}{{animation-delay:{0.5 + i * 0.53:.2f}s}}" for i in range(4))
        + f"@keyframes halo{{0%{{opacity:.55;transform:scale(1)}}70%,100%{{opacity:0;transform:scale(2.6)}}}}"
        f".halo{{transform-box:fill-box;transform-origin:center;animation:halo 2.8s {ease} 2.6s 3 both}}"
        + REDUCED + "@media (prefers-reduced-motion:reduce){.halo{display:none}}"
    )
    panel = f'<rect class="panel" x="{PANEL_X}" y="0" width="{W - 2 * PANEL_X}" height="{H}" rx="28" fill="{th["hero"]}"/>'
    # re-anchor the wide layout to the final height
    shift = H - 452
    if shift:
        wide_svg = f'<g class="w"><g transform="translate(0 {shift:g})">{wide_svg[len("<g class=\"w\">"):-4]}</g></g>'
    title = f"{name}. {eyebrow}. {statement} {status} · AWS Certified Cloud Practitioner · Pune, India."
    return svg_doc(W, H, title, defs + panel + wide_svg + narrow_svg, style), title


def headline(theme: str, text: str, eyebrow: str | None = None, sub: str | None = None,
             size: float = 48, gradient: bool = False, ident: str = "h", center: bool = False,
             lines_w: list[str] | None = None, x_left: float = 9):
    """Full-width section headline (846 units) with a phone layout via @media.

    Text is bottom-anchored so the space above it becomes section rhythm on desktop.
    The phone headline size is the largest (26px down to 21px real) that keeps the
    phone layout within the desktop height, so neither layout inflates the other."""
    th = THEMES[theme]
    W = 846
    X = W / 2 if center else x_left
    anchor = "middle" if center else None
    maxw = W - 2 * 9
    k = 846 / 308
    TOP_AIR = 48
    E_W, S_W = 19, 21              # desktop eyebrow / subhead sizes
    E_N, S_N = 13.5 * k, 14 * k    # phone eyebrow / subhead sizes

    wl = ([[(w, False) for w in ln.split(" ")] for ln in lines_w] if lines_w
          else wrap(text, size, maxw, 600, display=True))
    while not all(M.width(plain([l]), size, 600, display=True) <= maxw for l in wl):
        size -= 1  # designed breaks must survive the widest fallback face

    def stack(hs, n_lines, es, ss, n_sub):
        """Return relative baselines and total height for a layout."""
        y, marks = 0.0, {}
        if eyebrow:
            y += cap(es)
            marks["e"] = y
            y += es * 0.55
        y += cap(hs) + (es * 0.55 if eyebrow else 0)
        marks["h"] = [y + i * hs * 1.1 for i in range(n_lines)]
        y = marks["h"][-1]
        if sub:
            y += ss * 0.95 + cap(ss)
            marks["s"] = [y + i * ss * 1.3 for i in range(n_sub)]
            y = marks["s"][-1]
        return marks, y + hs * 0.26

    w_marks, w_h = stack(size, len(wl), E_W, S_W, 1)
    H = round(w_h + TOP_AIR)
    sub_n = wrap(sub, S_N, maxw, 400) if sub else []
    def narrow_at(real):
        ns = real * k * (1.08 if gradient else 1)
        lines = wrap(text, ns, maxw, 600, display=True)
        if lines_w and all(M.width(l, ns, 600, display=True) <= maxw for l in lines_w):
            lines = wl  # keep the designed line breaks on phones when they fit
        return (ns, lines, *stack(ns, len(lines), E_N, S_N, len(sub_n)))

    for real in [26, 25, 24, 23, 22, 21]:
        nsize, nl, n_marks, n_h = narrow_at(real)
        if n_h + 8 * k <= H:
            break
    else:  # nothing fits the desktop height: use a compact phone size and let the image grow a little
        nsize, nl, n_marks, n_h = narrow_at(22)
    H = round(max(H, n_h + 8 * k))

    def grad(gid, lines, s):
        if not gradient:
            return ""
        g0, g1 = th["grad"]
        ww = max(M.width(plain([l]), s, 600) for l in lines) / Measurer.SAFETY
        x1 = X - ww / 2 if center else X
        return (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{x1:g}" y1="0" x2="{x1 + ww:g}" y2="0">'
                f'<stop offset="0" stop-color="{g0}"/><stop offset="1" stop-color="{g1}"/></linearGradient>')

    def render(marks, total, lines, hs, es, ss, sub_lines, cls, gid):
        off = H - total - 3
        out = []
        if eyebrow:
            out.append(line_svg(eyebrow, X, round(marks["e"] + off, 1), round(es, 2), 600, th["fg2"], "d", anchor=anchor))
        fill = f"url(#{gid})" if gradient else th["fg"]
        for yy, ln in zip(marks["h"], lines):
            out.append(line_svg(ln, X - (1 if X > 0 and not center else 0), round(yy + off, 1), round(hs, 2), 600, fill, "d", anchor=anchor))
        if sub:
            for yy, ln in zip(marks["s"], sub_lines):
                out.append(line_svg(ln, X, round(yy + off, 1), round(ss, 2), 400, th["fg2"], "t", anchor=anchor))
        return f'<g class="{cls}">{"".join(out)}</g>'

    defs = f"<defs>{grad('gw', wl, size)}{grad('gn', nl, nsize)}</defs>" if gradient else ""
    body = (defs + render(w_marks, w_h, wl, size, E_W, S_W, [[(sub, False)]] if sub else [], "w", "gw")
            + render(n_marks, n_h, nl, nsize, E_N, S_N, sub_n, "n", "gn"))
    style = ".n{display:none}@media (max-width:640px){.w{display:none}.n{display:inline}}"
    title = " ".join(x for x in [eyebrow, text, sub] if x)
    return svg_doc(W, H, title, body, style, ident), title


# ---- tiles -----------------------------------------------------------------
@dataclass
class Tile:
    blocks_w: list[Block]
    blocks_n: list[Block] | None = None
    motif: str | None = None
    accent: tuple | None = None
    link: str | None = None   # footer link label (bottom-anchored)
    title: str = ""
    ident: str = "t"


def tile_svgs(tiles: list[Tile], W: int, theme: str, pad_w: float, pad_n: float | None = None,
              radius: float = 20, per_row: int = 1):
    """Render tiles; tiles sharing a desktop row (per_row) get equal heights. Returns [(svg, title)]."""
    th = THEMES[theme]
    INS = 6
    cw = W - 2 * INS
    results = []
    measured = []
    for t in tiles:
        acc = None
        if t.accent and t.accent[0]:
            acc = t.accent[0] if theme == "light" else t.accent[1]
        th2 = dict(th, acc=acc or th["link"])
        top_w = pad_w + (40 if t.motif else 0)
        sw, bw, _ = layout_blocks(t.blocks_w, INS + pad_w, top_w, cw - 2 * pad_w, th2, slack=pad_w - 4)
        need_w = bw + pad_w + (30 if t.link else 0)
        sn = bn = None
        need_n = 0
        if t.blocks_n:
            top_n = pad_n + (40 if t.motif else 0)
            sn, bn, _ = layout_blocks(t.blocks_n, INS + pad_n, top_n, cw - 2 * pad_n, th2, slack=pad_n - 4)
            need_n = bn + pad_n + (34 if t.link else 0)
            t._bn = bn
        measured.append((t, th2, sw, sn, need_w, need_n))
    heights = []
    for r0 in range(0, len(measured), per_row):
        row = measured[r0:r0 + per_row]
        h = round(max(max(m[4], m[5]) for m in row)) + INS  # bottom inset = row gutter
        heights += [h] * len(row)
    for (t, th2, sw, sn, _, _), H in zip(measured, heights):
        card = (f'<rect class="card" x="{INS}" y="0" width="{cw}" height="{H - INS}" rx="{radius}" '
                f'fill="{th["tile"]}" fill-opacity="{th["tile_op"]}"'
                + (f' stroke="{th["stroke"]}" stroke-opacity=".09" stroke-width="1"' if th["stroke"] != "none" else "")
                + "/>")
        body = card
        mot_w = mot_n = ""
        if t.motif:
            mot_w = motif(t.motif, W - INS - pad_w - 64, pad_w - 2, th2["acc"], th)
            if t.blocks_n:
                mot_n = motif(t.motif, W - INS - pad_n - 64, pad_n - 2, th2["acc"], th)
        foot_w = foot_n = ""
        if t.link:
            foot_w = line_svg(t.link + " ›", INS + pad_w, H - INS - pad_w + 2, 16, 400, th["link"], "t")
            if t.blocks_n:
                foot_n = line_svg(t.link + " ›", INS + pad_n, round(t._bn + 20 + cap(18.5), 1), 18.5, 400, th["link"], "t")
        style = ""
        if t.blocks_n:
            body += f'<g class="w">{mot_w}{sw}{foot_w}</g><g class="n">{mot_n}{sn}{foot_n}</g>'
            style = f".n{{display:none}}@media (max-width:{W - 21}px){{.w{{display:none}}.n{{display:inline}}}}"
        else:
            body += mot_w + sw + foot_w
        results.append((svg_doc(W, H, t.title, body, style, t.ident), t.title))
    return results


def stat_pair(stats, theme: str, H: int | None = None):
    """One 420-unit image holding two stat cards (4 stats -> 2 images -> 4-up/2x2).
    With H=None returns only the height needed, so pairs can share one height."""
    th = THEMES[theme]
    W, INS, GUT = 420, 6, 12
    cw = (W - 2 * INS - GUT) / 2
    pad = 22
    layouts = {"w": dict(num=46, lab=17, lab_lh=22, det=15, det_lh=20, pad=22),
               "n": dict(num=54, lab=21, lab_lh=26, det=18, det_lh=23, pad=18)}
    rendered, need = {}, 0
    for mode, L in layouts.items():
        parts = []
        for j, (num, lab, det) in enumerate(stats):
            x0 = INS + j * (cw + GUT)
            th2 = th
            blocks = [Block(num, L["num"], L["num"], 600, "fg", fam="d", nowrap=True),
                      Block(lab, L["lab"], L["lab_lh"], 600, "fg", gap=L["num"] * 0.32),
                      Block(det, L["det"], L["det_lh"], 400, "fg2", gap=L["det"] * 0.42)]
            s, bottom, _ = layout_blocks(blocks, x0 + L["pad"], L["pad"] + 4, cw - 2 * L["pad"], th2, slack=L["pad"] - 6)
            parts.append(s)
            need = max(need, bottom + L["pad"])
        rendered[mode] = "".join(parts)
    if H is None:
        return round(need) + INS
    cards = "".join(f'<rect x="{INS + j * (cw + GUT):g}" y="0" width="{cw:g}" height="{H - INS}" rx="20" '
                    f'fill="{th["tile"]}" fill-opacity="{th["tile_op"]}"'
                    + (f' stroke="{th["stroke"]}" stroke-opacity=".09"' if th["stroke"] != "none" else "") + "/>"
                    for j in range(2))
    body = cards + f'<g class="w">{rendered["w"]}</g><g class="n">{rendered["n"]}</g>'
    style = ".n{display:none}@media (max-width:399px){.w{display:none}.n{display:inline}}"
    title = " · ".join(f"{n}: {l}, {d}" for n, l, d in stats)
    return svg_doc(W, H, title, body, style, "s"), title


def pill(label: str, theme: str, filled: bool, side: str):
    """Apple-style pill button, 44 units tall. `side` adds a 7-unit gutter on that side."""
    th = THEMES[theme]
    size = 17
    tw = M.width(label, size, 400) / Measurer.SAFETY
    pw = round(tw + 42)  # 21 per side; centred text absorbs wider fallbacks
    gut = 6
    W = pw + gut
    x0 = gut if side == "left" else 0
    if filled:
        shape = f'<rect x="{x0}" y="0" width="{pw}" height="44" rx="22" fill="{th["fill"]}"/>'
        col = th["on_fill"]
    else:
        shape = (f'<rect x="{x0 + 0.75}" y="0.75" width="{pw - 1.5}" height="42.5" rx="21.25" '
                 f'fill="none" stroke="{th["link"]}" stroke-width="1.5"/>')
        col = th["link"]
    text = line_svg(label, x0 + pw / 2, 28, size, 400, col, "t", anchor="middle")
    return svg_doc(W, 44, label, shape + text, "", "p"), label, W


# ---------------------------------------------------------------- content
REPOS = [
    dict(key="autoswe", slug="Autonomous-AI-Software-Engineering-Platform", name="AutoSWE", lang="Python",
         desc="AutoSWE: multi-agent LLM platform (Claude) that turns a plain-English spec into a validated, deployable project: FastAPI code, tests, Dockerfile, CI, Kubernetes and Terraform. Live agent progress UI, offline mode, 150+ tests."),
    dict(key="securecart", slug="SecureCart-Cloud-Native-Security-Enhanced-eCommerce-Platform", name="SecureCart", lang="TypeScript",
         desc="Security-focused full-stack e-commerce platform: Django REST + React/TypeScript. Rotating httpOnly refresh tokens, RBAC, oversell-proof transactional checkout, audit log, CSP. 229 tests, Dockerized, CI."),
    dict(key="microservices", slug="secure-cloud-microservices-platform", name="Secure Cloud Microservices Platform", lang="Python",
         desc="Secure cloud-native microservices: Python (Django) auth service issuing JWTs via JWKS + Java 21 Spring Boot orders service, behind a Traefik gateway, with Prometheus/Grafana, Kubernetes manifests, GitHub Actions + Jenkins CI/CD, Trivy scans and a 26-test e2e suite."),
    dict(key="multitenant", slug="secure-multi-tenant-platform", name="Secure Multi-Tenant Platform", lang="Python",
         desc="Multi-tenant SaaS backend (Django REST Framework): fail-closed tenant isolation, RBAC, expiring invitations, hardened JWT and an append-only audit log, with a 228-test suite that proves cross-tenant isolation."),
    dict(key="momentum", slug="Momentum-Live-Stock-Tracker", name="Momentum Live Stock Tracker", lang="Python",
         desc="Streamlit dashboard for global stocks, indices, FX and crypto: candlestick charts, tested technical indicators (SMA/EMA/RSI/MACD/Bollinger), comparison and watchlist. Typed, 94% test coverage, Dockerized."),
]

STATS = [
    ("99.9%", "Uptime at $0 hosting cost", "EcoQuest"),
    ("↓ 90%", "Deployment downtime", "20 min → under 2 min on EC2"),
    ("↓ 40%", "Database read latency", "MongoDB indexing + caching"),
    ("10+ hrs", "Saved every week", "Airflow ETL automation"),
]

CAPS = [
    ("Build", "Django · Node.js · React",
     "Full-stack apps, REST APIs and real-time WebSocket engines handling **50+ live sessions**"),
    ("Ship", "Jenkins · GitHub Actions · Docker",
     "CI/CD pipelines and zero-downtime releases that cut deploy downtime **from 20 min to under 2**"),
    ("Run", "AWS · Linux · Bash",
     "AWS EC2, S3, IAM, VPC and RDS, with Linux process management and Bash automation"),
    ("Automate", "PostgreSQL · MongoDB · Go",
     "Airflow ETL pipelines and Go ingestion services that **save 10+ hours a week**"),
    ("Secure & Observe", "Grafana · Wazuh",
     "JWT, RBAC, rate limiting and IAM policies, plus Grafana alerting and Wazuh SIEM"),
    ("Extend with AI", "Claude AI",
     "Claude-powered personalization with safety filtering, plus GenAI and RAG fundamentals"),
]

STACK = [
    ("Languages", "Python · Java · JavaScript · TypeScript · Go · Bash", None),
    ("Backend", "Django · Node.js · Express · FastAPI · Spring Boot",
     "Django REST Framework · RESTful APIs · WebSockets (Socket.io) · SQLAlchemy · Flyway · OpenAPI"),
    ("Frontend", "React · TypeScript · Tailwind · HTML · CSS",
     "React 18 · Zustand · Progressive Web Apps · Vite · TanStack Query · React Hook Form + Zod"),
    ("Cloud & DevOps", "AWS · Docker · Jenkins · GitHub Actions · Linux · Git · GitHub",
     "AWS EC2 · S3 · IAM · VPC · RDS · Linux process management"),
    ("Platform & IaC", "Kubernetes · Terraform · Traefik · Nginx",
     "Docker Compose · Kustomize · network policies · gunicorn"),
    ("Data & Orchestration", "PostgreSQL · MongoDB · Apache Airflow · Redis · SQLite",
     "ETL pipelines · MongoDB Atlas · Hadoop / Spark (exposure) · Streamlit · Plotly · pandas · NumPy"),
    ("Security & Observability", "Grafana · Wazuh SIEM · Prometheus",
     "JWT auth · RBAC · rate limiting · Helmet · CORS · IAM policies · OAuth2 / JWKS · Argon2 · CSP · Trivy · pip-audit"),
    ("AI / ML", "Claude AI · Generative AI · RAG", "Supervised & unsupervised learning · model evaluation metrics"),
    ("AI agents & LLMs", "Multi-agent pipelines · MCP · tool calling",
     "Anthropic & OpenAI-compatible APIs · Ollama · embeddings & semantic search · agent memory · LLM evals"),
    ("Testing & Quality", "pytest · Vitest · Playwright · JUnit 5 · Testcontainers",
     "ruff · mypy (strict) · ESLint · Prettier · axe accessibility checks"),
    ("Currently exploring", "Machine Learning, Computer Vision and Generative AI (RAG)", None),
    ("Ask me about", "CI/CD pipelines · Django & Node.js backends · AWS · SIEM monitoring", None),
]

EDU = [
    ("Education", "B.Tech, Cloud Technology & Information Security", "Ajeenkya D Y Patil University, Pune · 2022 – 2026",
     "Cloud Computing · Network Security · Information Security · Operating Systems · DBMS · Software Engineering · Data Structures & Algorithms"),
    ("Certification", "AWS Certified Cloud Practitioner", "Amazon Web Services · Apr 2026 – Apr 2029",
     "EC2 · S3 · IAM · VPC networking · security groups · load balancing · cloud deployment best practices"),
]

EMAIL = "arya.mahindrakar.09@gmail.com"
CTA_HTML: list[str] = []
GH = "https://github.com/Arya-9989"


# ---------------------------------------------------------------- README assembly
def write(name: str, svgs: dict[str, str]):
    for theme, s in svgs.items():
        (ASSETS / f"{name}-{theme}.svg").write_text(s, encoding="utf-8")


def pic(name: str, width: str, alt: str) -> str:
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="assets/{name}-dark.svg">'
            f'<img src="assets/{name}-light.svg" width="{width}" alt="{esc(alt)}"></picture>')


def build():
    ASSETS.mkdir(exist_ok=True)
    md = []

    # hero
    out = {t: hero(t) for t in THEMES}
    write("hero", {t: v[0] for t, v in out.items()})
    md.append(f'<p>{pic("hero", "100%", out["light"][1])}</p>')

    # calls to action
    def ctas():
        e = {t: pill("Email me", t, True, "right") for t in THEMES}
        r = {t: pill("Browse my repos", t, False, "left") for t in THEMES}
        write("cta-email", {t: v[0] for t, v in e.items()})
        write("cta-repos", {t: v[0] for t, v in r.items()})
        return (f'<p align="center"><a href="mailto:{EMAIL}">{pic("cta-email", str(e["light"][2]), "Email me")}</a>'
                f'<a href="{GH}?tab=repositories">{pic("cta-repos", str(r["light"][2]), "Browse my repos")}</a></p>')
    cta = ctas()
    md.append(cta)
    CTA_HTML.append(cta)

    def head(name, text, **kw):
        o = {t: headline(t, text, **kw) for t in THEMES}
        write(name, {t: v[0] for t, v in o.items()})
        return f'<p>{pic(name, "100%", o["light"][1])}</p>'

    # impact
    md.append("<!-- Impact -->")
    md.append(head("h-impact", "Impact at a glance."))
    pairs = []
    chunks = [STATS[:2], STATS[2:]]
    sh = max(stat_pair(c, t) for c in chunks for t in THEMES)
    for i, chunk in enumerate(chunks):
        o = {t: stat_pair(chunk, t, sh) for t in THEMES}
        write(f"impact-{i + 1}", {t: v[0] for t, v in o.items()})
        pairs.append(pic(f"impact-{i + 1}", "420", o["light"][1]))
    md.append(f'<p align="center">{"".join(pairs)}</p>')

    # about
    md.append("<!-- About -->")
    md.append(head("h-about", "I turn code into reliable, secure production systems.", eyebrow="About me", size=56,
                   center=True, lines_w=["I turn code into reliable,", "secure production systems."]))
    md.append("<p align=\"center\">I work across the whole path to production: I write the backend, build the pipeline that ships it, "
              "run it on AWS, and set up the monitoring and security that keep it healthy. "
              "Then I measure the result and make it faster.</p>")
    md.append(head("h-what", "What I do.", sub="DevOps · Cloud · Security · AI Integrations"))
    tiles = []
    for i, (title, tech, text) in enumerate(CAPS):
        tiles.append(Tile([Block(tech, 13, 18, 600, "fg2", list_mode=True),
                           Block(title, 22, 27, 600, "fg", gap=10, fam="d"),
                           Block(text, 15, 21, 400, "fg2", gap=9, bold_color="fg")],
                          title=f"{title}. {text.replace('**', '')} ({tech})", ident=f"c{i}"))
    md.append(group("cap", tiles, 280, pad_w=22))

    # stack
    md.append("<!-- Tech stack -->")
    md.append(head("h-stack", "Tech stack."))
    tiles = []
    for i, (lab, items, det) in enumerate(STACK):
        bl = [Block(lab, 13, 18, 600, "fg2"), Block(items, 17, 23, 600, "fg", gap=9, list_mode=True)]
        if det:
            bl.append(Block(det, 14, 19, 400, "fg2", gap=9, list_mode=True))
        tiles.append(Tile(bl, title=f"{lab}: {items}" + (f". {det}" if det else ""), ident=f"k{i}"))
    md.append(group("stack", tiles, 280, pad_w=22))

    # repositories
    md.append("<!-- Open-source repositories -->")
    md.append(head("h-repos", "Open-source repositories."))
    tiles, links = [], []
    for r in REPOS:
        acc = REPO_ACCENT[r["key"]]
        bw = [Block(r["lang"], 14, 18, 600, "acc"),
              Block(r["name"], 26, 31, 600, "fg", gap=10, fam="d"),
              Block(r["desc"], 16.5, 24, 400, "fg2", gap=11)]
        bn = [Block(r["lang"], 17, 21, 600, "acc"),
              Block(r["name"], 28, 33, 600, "fg", gap=9, fam="d"),
              Block(r["desc"], 18.5, 25.5, 400, "fg2", gap=11)]
        tiles.append(Tile(bw, bn, motif=r["key"], accent=acc, link="View on GitHub",
                          title=f"{r['name']} ({r['lang']}). {r['desc']}", ident=f"r{r['key']}"))
        links.append(f"{GH}/{r['slug']}")
    tiles.append(Tile([Block("GitHub", 14, 18, 600, "fg2"),
                       Block("Browse my repos", 26, 31, 600, "fg", gap=10, fam="d"),
                       Block("github.com/Arya-9989", 16.5, 24, 400, "fg2", gap=11)],
                      [Block("GitHub", 17, 21, 600, "fg2"),
                       Block("Browse my repos", 28, 33, 600, "fg", gap=9, fam="d"),
                       Block("github.com/Arya-9989", 18.5, 25.5, 400, "fg2", gap=11)],
                      motif="more", accent=(None, None), link="View all repositories",
                      title="Browse my repos on GitHub: github.com/Arya-9989", ident="rmore"))
    links.append(f"{GH}?tab=repositories")
    md.append(group("repo", tiles, 420, pad_w=30, pad_n=28, radius=24, links=links,
                    names=[r["key"] for r in REPOS] + ["more"]))

    md.append("<!-- Featured projects -->")
    md.append(head("h-projects", "Featured projects.", x_left=0))
    md.append("@@PROJECTS@@")

    # education
    md.append("<!-- Education -->")
    md.append(head("h-edu", "Education & certification."))
    tiles = []
    for i, (eb, title, org, det) in enumerate(EDU):
        tiles.append(Tile([Block(eb, 14, 18, 600, "fg2"),
                           Block(title, 24, 29, 600, "fg", gap=10, fam="d"),
                           Block(org, 16, 22, 600, "fg", gap=10, list_mode=True),
                           Block(det, 15, 21, 400, "fg2", gap=12, list_mode=True)],
                          [Block(eb, 17, 21, 600, "fg2"),
                           Block(title, 27, 32, 600, "fg", gap=9, fam="d"),
                           Block(org, 18.5, 25, 600, "fg", gap=9, list_mode=True),
                           Block(det, 17.5, 24, 400, "fg2", gap=11, list_mode=True)],
                          title=f"{eb}: {title}. {org}. {det}", ident=f"e{i}"))
    md.append(group("edu", tiles, 420, pad_w=30, pad_n=28, radius=24, names=["degree", "aws"]))

    # motto + contact
    md.append("<!-- Contact -->")
    md.append(head("h-motto", "Secure by design, scalable by default.", eyebrow="Motto", size=64, gradient=True,
                   center=True, lines_w=["Secure by design,", "scalable by default."]))
    md.append(head("h-contact", "Let’s work together.", center=True))
    return md


def group(prefix, tiles, W, pad_w, pad_n=None, radius=20, links=None, names=None):
    per_row = 846 // W
    by_theme = {t: tile_svgs(tiles, W, t, pad_w, pad_n, radius, per_row) for t in THEMES}
    items = []
    for i in range(len(tiles)):
        nm = f"{prefix}-{names[i] if names else i + 1}"
        write(nm, {t: by_theme[t][i][0] for t in THEMES})
        p = pic(nm, str(W), by_theme["light"][i][1])
        items.append(f'<a href="{links[i]}">{p}</a>' if links else p)
    return f'<p align="center">{"".join(items)}</p>'


def main():
    global M
    with sync_playwright() as p:
        b = p.chromium.launch()
        M = Measurer(b.new_page())
        md = build()
        b.close()
    template = (ROOT / "scripts" / "README.template.md").read_text(encoding="utf-8")
    parts = "\n\n".join(md)
    head_part, tail_part = parts.split("@@PROJECTS@@")
    out = template.replace("@@TOP@@", head_part.strip()).replace("@@BOTTOM@@", tail_part.strip())
    out = out.replace("@@CTA@@", CTA_HTML[0])
    (ROOT / "README.md").write_text(out, encoding="utf-8", newline="\n")
    print("wrote README.md and", len(list(ASSETS.glob("*.svg"))), "SVGs")


if __name__ == "__main__":
    main()
