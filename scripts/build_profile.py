#!/usr/bin/env python3
"""Build the profile README and its self-hosted SVG artwork.

    python scripts/build_profile.py            # write README.md and assets/*.svg
    svgo --config scripts/svgo.config.mjs -q -f assets
    python scripts/build_profile.py --check    # validate the optimised assets

Needs `pip install playwright` (plus `playwright install chromium`). The first run
downloads three measuring fonts into scripts/.cache. Repository descriptions are
read live with the GitHub CLI (or the public API) and fall back to REPOS below.

Every SVG has a light and a dark variant. The README picks one with
<picture><source media="(prefers-color-scheme: dark)">, which GitHub's
<themed-picture> also maps onto the viewer's GitHub theme.

Layout without README CSS
  * One centred column. The hero and the headlines are 846 units wide (the
    profile README column from 1280 px up) and scale down below that. Tile
    groups are centred paragraphs of fixed-width images. On a wider column
    (the blob page reaches 1012 px) everything stays one 846-wide composition.
  * Tiles are 280 (3 per row) or 420 (2 per row) wide. The README column runs
    continuously from 238 px (320 px phone) to 846, so a group of 280 tiles
    flows 3-up, 2-up or 1-up. Heights are shared over runs of 6 tiles for 280
    (true for both flows) and pairs for 420.
  * 420 tiles and stat pairs carry a phone layout (<= 399 px), the hero and the
    headlines a medium (421-640 px) and a phone (<= 420 px) layout, switched by
    @media on the rendered image width. An image has one aspect ratio, so a run
    of tiles is as tall as its tallest layout needs; each layout then takes the
    largest type scale that fits, and no text is under 11 px on a 238 px column.
    280 tiles have no phone layout. On a 238 px column they scale to 85%, which
    keeps their smallest text at 11 px.
  * Media queries that combine width with prefers-color-scheme are not used:
    <themed-picture> rewrites any source mentioning the colour scheme.

Text fitting
  SVG text in an <img> uses the viewer's system font. Every line is measured in
  Chromium with Segoe UI Variable, Segoe UI and Arial (Windows; Arial is metric-
  compatible with Liberation Sans on Linux), and with Inter (standing in for
  SF Pro, which it slightly out-widths), Roboto (Android) and DejaVu Sans
  (minimal Linux). A line fits when every face but DejaVu fits the measure and
  DejaVu may run into the right padding but stays clear of the card edge.

Motion (CSS inside the SVG; GitHub allows no script)
  Every animation runs once (Chromium starts it on load, Firefox and Safari when
  the image first comes into view) and ends on the static design. Keyframes
  carry only the `from` state, fill is `backwards`, and the base style is the
  final frame, so a renderer without animation, or a capture after the motion,
  shows the complete design. Every SVG carries a prefers-reduced-motion rule
  that removes all animation. Browsers honour a real OS setting inside <img> in
  Chromium and Firefox. DevTools emulation does not reach into <img>, so test
  with --force-prefers-reduced-motion. The longest sequence ends before 5 s.
"""
from __future__ import annotations

import base64
import html
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
CACHE = ROOT / "scripts" / ".cache" / "fonts"
GH_USER = "Arya-9989"
GH = f"https://github.com/{GH_USER}"
EMAIL = "arya.mahindrakar.09@gmail.com"

COL = 846           # README column at >= 1280 px
SMALL_COL = 238     # README column on a 320 px phone
MIN_PX = 11         # smallest text, in real px, on the smallest column

# ---------------------------------------------------------------- type & colour
DISPLAY = ("-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI Variable Display', "
           "'Segoe UI', Inter, Roboto, 'Helvetica Neue', Helvetica, Arial, Arimo, 'Liberation Sans', 'Nimbus Sans', sans-serif")
TEXT = ("-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI Variable Text', "
        "'Segoe UI', Inter, Roboto, 'Helvetica Neue', Helvetica, Arial, Arimo, 'Liberation Sans', 'Nimbus Sans', sans-serif")
MONO = "ui-monospace, 'SF Mono', 'Cascadia Code', Consolas, Menlo, 'Liberation Mono', monospace"

THEMES = {
    "light": dict(fg="#1d1d1f", fg2="#6e6e73", tile="#f5f5f7", tile_op="1", stroke="none",
                  hero="#f5f5f7", hair="#d2d2d7", link="#0066cc", fill="#0071e3", ring="#c7c7cc",
                  grad=("#0066cc", "#0b7a96"), on_fill="#ffffff", spark="#8cc8ff", green="#248a3d"),
    # dark link and accents pass AA on the tile in GitHub's dark, dark dimmed and high-contrast themes
    "dark": dict(fg="#f5f5f7", fg2="#a1a1a6", tile="#ffffff", tile_op="0.06", stroke="#ffffff",
                 hero="#000000", hair="#3a3a3c", link="#47a3ff", fill="#0071e3", ring="#48484a",
                 grad=("#5ab4ff", "#5fd4e2"), on_fill="#ffffff", spark="#d6ecff", green="#30d158"),
}

# Per-repo identity accents (light, dark): motif and eyebrow only.
REPO_ACCENT = {
    "autoswe": ("#5e5ce6", "#9a97ff"),
    "securecart": ("#0040dd", "#6aa6ff"),
    "microservices": ("#086f8c", "#3fd0ea"),
    "multitenant": ("#0f766e", "#3dd6c1"),
    "momentum": ("#1d7a34", "#30d158"),
}

# ---------------------------------------------------------------- motion tokens
EASE = "cubic-bezier(.4,0,.6,1)"        # standard
EASE_IN = "cubic-bezier(.16,1,.3,1)"    # entrances (no overshoot)
REDUCED = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
MOTIF_DELAY = 0.7    # s; motifs move once, after the tile entrance, and are still by 2.5 s


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
FONT_SOURCES = {  # pinned web fonts that stand in for the faces a viewer may have
    "M-Inter": [("https://cdn.jsdelivr.net/npm/@fontsource-variable/inter@5.3.0/files/inter-latin-wght-normal.woff2", "100 900")],
    "M-Roboto": [("https://cdn.jsdelivr.net/npm/@fontsource-variable/roboto@5.3.0/files/roboto-latin-wght-normal.woff2", "100 900")],
    "M-DejaVu": [("https://cdn.jsdelivr.net/npm/@fontsource/dejavu-sans@5.3.0/files/dejavu-sans-latin-400-normal.woff2", "400"),
                 ("https://cdn.jsdelivr.net/npm/@fontsource/dejavu-sans@5.3.0/files/dejavu-sans-latin-700-normal.woff2", "700")],
}
LOCAL = {"t": ["Segoe UI Variable Text", "Segoe UI", "Arial"],
         "d": ["Segoe UI Variable Display", "Segoe UI", "Arial"],
         "m": ["Cascadia Code", "Consolas", "Courier New"]}
WEB_PRIMARY = ["M-Inter", "M-Roboto"]
FALLBACK = ["M-DejaVu"]


def font_file(url: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / url.rsplit("/", 1)[1]
    if not p.exists():
        print("downloading", url)
        with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 (pinned https URL)
            p.write_bytes(r.read())
    return p


class Measurer:
    PRIMARY_MARGIN = 1.01  # other engines shape a hair differently from Chromium

    def __init__(self, page):
        self.page = page
        self.cache: dict[tuple, tuple[float, float]] = {}
        faces = []
        for fam, srcs in FONT_SOURCES.items():
            for url, w in srcs:
                b64 = base64.b64encode(font_file(url).read_bytes()).decode()
                faces.append(f'@font-face{{font-family:"{fam}";src:url(data:font/woff2;base64,{b64}) format("woff2");font-weight:{w}}}')
        page.set_content(f"<style>{''.join(faces)}</style><canvas id=c></canvas>")
        page.evaluate("""fams => Promise.all(fams.flatMap(f => ['400','600','700'].map(w => document.fonts.load(`${w} 20px "${f}"`))))""",
                      list(FONT_SOURCES))
        # keep only local faces that exist on this machine
        present = page.evaluate("""fams => fams.filter(f => { const c = document.getElementById('c').getContext('2d');
              const m = g => { c.font = `600 40px "${f}", ${g}`; return c.measureText('Arya Mahindrakar 0123').width; };
              return m('monospace') === m('serif'); })""", sorted({f for v in LOCAL.values() for f in v}))
        self.local = {k: [f for f in v if f in present] for k, v in LOCAL.items()}
        missing = sorted({f for v in LOCAL.values() for f in v} - set(present))
        if missing:
            print("note: local faces not installed, measured without them:", ", ".join(missing))

    def width(self, text: str, size: float, weight: int = 400, fam: str = "t") -> tuple[float, float]:
        """(widest primary face, widest fallback face) in user units."""
        key = (text, size, weight, fam)
        if key not in self.cache:
            prim = self.local[fam] + ([] if fam == "m" else WEB_PRIMARY)
            fb = [] if fam == "m" else FALLBACK
            ws = self.page.evaluate(
                """([t, s, w, fams, ls]) => { const c = document.getElementById('c').getContext('2d');
                     return fams.map(f => { c.font = `${w} ${s}px "${f}"`; c.letterSpacing = ls + 'px';
                                             return c.measureText(t).width; }); }""",
                [text, size, weight, prim + fb, tracking(size)])
            p = max(ws[:len(prim)]) * self.PRIMARY_MARGIN
            self.cache[key] = (p, max(ws[len(prim):]) if fb else p)
        return self.cache[key]

    def fits(self, text, size, weight, fam, maxw, slack=0.0) -> bool:
        p, f = self.width(text, size, weight, fam)
        return p <= maxw and f <= maxw + slack

    def ref(self, text, size, weight=400, fam="t") -> float:
        """Width in the reference face (Windows' Segoe), for centring and gradients."""
        f = (self.local[fam] or WEB_PRIMARY)[0]
        return self.page.evaluate("""([t, s, w, f, ls]) => { const c = document.getElementById('c').getContext('2d');
              c.font = `${w} ${s}px "${f}"`; c.letterSpacing = ls + 'px'; return c.measureText(t).width; }""",
                                  [text, size, weight, f, tracking(size)])


M: Measurer  # set in main()
NB = " "


def tokens_for(text: str, list_mode: bool) -> list[str]:
    if list_mode and " · " in text:
        items = text.split(" · ")
        return [it.replace(" ", NB) + (NB + "·" if i < len(items) - 1 else "") for i, it in enumerate(items)]
    return text.split(" ")


def parse_rich(text: str) -> list[tuple[str, bool]]:
    """'plain **bold** plain' -> [(word, bold), ...]."""
    out, prev = [], " "
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        ws = part.split()
        if ws and out and not part[:1].isspace() and not prev[-1:].isspace():
            # punctuation right after bold text stays on its word (and takes its weight)
            out[-1] = (out[-1][0] + ws.pop(0), out[-1][1])
        for w in ws:
            out.append((w, i % 2 == 1))
        prev = part or prev
    return out


def wrap(text: str, size: float, maxw: float, weight: int = 400, list_mode: bool = False,
         bold_weight: int = 600, fam: str = "t", slack: float = 0) -> list[list[tuple[str, bool]]]:
    """Balanced wrap: fewest lines, then least raggedness. Returns lines of (word, bold) runs."""
    words = parse_rich(text) if "**" in text else [(t, False) for t in tokens_for(text, list_mode)]

    def seg_w(line, idx):
        tot = 0.0
        for j, (x, b) in enumerate(line):
            last = j == len(line) - 1
            if last and x.endswith(NB + "·"):
                x = x[:-2]
            tot += M.width(x.replace(NB, " ") + ("" if last else " "), size, bold_weight if b else weight, fam)[idx]
        return tot

    def fits(line):
        return seg_w(line, 0) <= maxw and seg_w(line, 1) <= maxw + slack

    expanded = []  # a list item longer than the line may break between its own words
    for wd in words:
        if NB in wd[0] and not fits([wd]):
            parts = wd[0].split(NB)
            if parts[-1] == "·":
                parts = parts[:-2] + [parts[-2] + NB + "·"]
            expanded += [(x, wd[1]) for x in parts]
        else:
            expanded.append(wd)
    words = expanded
    n, INF = len(words), float("inf")
    best = [(0.0, n)] * (n + 1)
    for i in range(n - 1, -1, -1):
        cand = (INF, n)
        for j in range(i + 1, n + 1):
            ln = words[i:j]
            if j > i + 1 and not fits(ln):
                break
            s = max(0.0, maxw - seg_w(ln, 0))
            cost = maxw * maxw * 4 + s * s * (0.35 if j == n else 1.0) + best[j][0]
            if j == n and j - i == 1 and n > 5:
                cost += maxw * maxw  # no single-word last line
            if cost < cand[0]:
                cand = (cost, j)
        best[i] = cand
    lines, i = [], 0
    while i < n:
        j = best[i][1]
        lines.append(words[i:j])
        i = j
    cleaned = []
    for ln in lines:
        x, b = ln[-1]
        if x.endswith(NB + "·"):
            ln = ln[:-1] + [(x[:-2], b)]
        cleaned.append(ln)
    for ln in cleaned:
        assert fits(ln) or len(ln) == 1, f"overflow: {ln}"
    return cleaned


def plain(lines) -> str:
    return " ".join(" ".join(w for w, _ in ln) for ln in lines).replace(NB, " ")


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
        parts.append(f'<tspan font-weight="{bold_weight}" fill="{bold_fill or fill}">{s}</tspan>' if b else s)
    return f"<text {attrs}>{''.join(parts)}</text>"


def svg_doc(w, h, title, body, style="", ident="t"):
    css = f".d{{font-family:{DISPLAY}}}.t{{font-family:{TEXT}}}.m{{font-family:{MONO}}}" + style + REDUCED
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:g}" height="{h:g}" viewBox="0 0 {w:g} {h:g}" '
            f'role="img" aria-labelledby="{ident}">'
            f'<title id="{ident}">{esc(title)}</title><style>{css}</style>{body}</svg>\n')


def cap(size):  # cap height of the system faces
    return size * 0.71


def speech(s: str) -> str:
    """Alt text that reads well aloud: list dots become commas, arrows become words."""
    s = s.replace("**", "").replace(NB, " ")
    s = re.sub(r"\s*·\s*", ", ", s)
    s = s.replace("↓ ", "down ").replace(" → ", " to ").replace("→", " to ").replace(" – ", " to ")
    return re.sub(r"\s+", " ", s).strip()


def rise(name="e", dist=12, dur=0.6):
    return f"@keyframes {name}{{from{{opacity:0;transform:translateY({dist}px)}}}}"


# ---------------------------------------------------------------- text stack layout
@dataclass
class Block:
    text: str
    size: float
    lh: float
    weight: int = 400
    color: str = "fg"          # theme key or literal colour
    gap: float = 0             # space above this block
    fam: str = "t"
    list_mode: bool = False
    bold_color: str = "fg"
    nowrap: bool = False


def layout_blocks(blocks: list[Block], x: float, top: float, maxw: float, th: dict, slack: float = 0):
    """Stack blocks from `top`. Returns (svg, bottom_y)."""
    out, y, first = [], top, True
    for bl in blocks:
        if bl.nowrap:
            while not M.fits(bl.text, bl.size, bl.weight, bl.fam, maxw, slack):
                bl = Block(**{**bl.__dict__, "size": round(bl.size - 1, 1), "lh": bl.lh - 1})
            lines = [[(bl.text, False)]]
        else:
            lines = wrap(bl.text, bl.size, maxw, bl.weight, bl.list_mode, fam=bl.fam, slack=slack)
        col = th.get(bl.color, bl.color)
        bcol = th.get(bl.bold_color, bl.bold_color)
        y += 0 if first else bl.gap
        base = y + cap(bl.size)
        for i, ln in enumerate(lines):
            out.append(line_svg(ln, x, round(base + i * bl.lh, 1), round(bl.size, 2), bl.weight, col, bl.fam, bcol))
        y = base + (len(lines) - 1) * bl.lh + bl.size * 0.24  # descender allowance
        first = False
    return "".join(out), y


# ---------------------------------------------------------------- motifs
def motif(kind: str, x: float, y: float, accent: str, th: dict, animate: bool) -> tuple[str, str]:
    """Line-art identity glyph in a 64x36 box at (x, y). Returns (svg, css).

    The animated version plays one slow cycle and comes to rest on the static glyph."""
    s = f'stroke="{accent}" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"'
    D0 = MOTIF_DELAY
    css = ""
    if kind == "autoswe":  # five-agent pipeline: a token passes along the agents
        out = f'<path d="M{x + 8:g} {y + 18:g}H{x + 56:g}" {s} opacity=".45"/>'
        for i in range(5):
            cx = x + 4 + i * 14
            out += (f'<circle cx="{cx:g}" cy="{y + 18:g}" r="4" fill="{accent}"/>' if i == 4
                    else f'<circle cx="{cx:g}" cy="{y + 18:g}" r="4" {s}/>')
            if animate and i < 4:
                out += f'<circle class="mt mt{i}" cx="{cx:g}" cy="{y + 18:g}" r="4" fill="{accent}" opacity="0"/>'
        if animate:
            css = (f"@keyframes mt{{0%{{opacity:0}}35%{{opacity:1}}100%{{opacity:0}}}}.mt{{animation:mt .55s {EASE} {D0}s backwards}}"
                   + "".join(f".mt{i}{{animation-delay:{D0 + i * 0.18:.2f}s}}" for i in range(4)))
        return out, css
    if kind == "securecart":  # bag whose lock closes
        out = (f'<path d="M{x + 18:g} {y + 12:g}h28l2 22H{x + 16:g}z" {s}/>'
               f'<path class="ms" d="M{x + 25:g} {y + 12:g}v-2a7 7 0 0 1 14 0v2" {s}/>'
               f'<circle cx="{x + 32:g}" cy="{y + 21:g}" r="2.6" fill="{accent}"/><path d="M{x + 32:g} {y + 23:g}v5" {s}/>')
        if animate:
            css = f"@keyframes ms{{from{{transform:translateY(-4px)}}}}.ms{{animation:ms .5s {EASE_IN} {D0 + 0.2}s backwards}}"
        return out, css
    if kind == "microservices":  # gateway fanning out to services: requests travel each route
        g = f'<rect x="{x + 2:g}" y="{y + 11:g}" width="14" height="14" rx="4" fill="{accent}"/>'
        routes = "".join(f'<path d="M{x + 16:g} {y + 18:g}C{x + 30:g} {y + 18:g} {x + 30:g} {y + 4 + i * 14:g} {x + 44:g} {y + 4 + i * 14:g}" {s} opacity=".55"/>' for i in range(3))
        reqs = "".join(f'<path class="mr mr{i}" d="M{x + 16:g} {y + 18:g}C{x + 30:g} {y + 18:g} {x + 30:g} {y + 4 + i * 14:g} {x + 44:g} {y + 4 + i * 14:g}" '
                       f'stroke="{accent}" stroke-width="2.4" fill="none" stroke-linecap="round" pathLength="1" stroke-dasharray=".18 1.2" stroke-dashoffset="-1.2"/>' for i in range(3)) if animate else ""
        nodes = "".join(f'<circle cx="{x + 50:g}" cy="{y + 4 + i * 14:g}" r="4.5" {s}/>' for i in range(3))
        if animate:
            css = (f"@keyframes mr{{from{{stroke-dashoffset:.18}}}}.mr{{animation:mr .8s {EASE} {D0}s backwards}}"
                   + "".join(f".mr{i}{{animation-delay:{D0 + i * 0.15:.2f}s}}" for i in range(3)))
        return g + routes + reqs + nodes, css
    if kind == "multitenant":  # sealed, separate spaces: each seals in turn
        out = "".join(f'<rect class="mm mm{i}" x="{x + 1 + i * 22:g}" y="{y + 8:g}" width="18" height="20" rx="5" '
                      + (f'fill="{accent}"/>' if i == 1 else f'{s}/>') for i in range(3))
        if animate:
            css = (f"@keyframes mm{{from{{opacity:.15;transform:scale(.82)}}}}"
                   f".mm{{transform-box:fill-box;transform-origin:center;animation:mm .45s {EASE_IN} {D0}s backwards}}"
                   + "".join(f".mm{i}{{animation-delay:{D0 + i * 0.16:.2f}s}}" for i in range(3)))
        return out, css
    if kind == "momentum":  # price sparkline draws in, then the last price lands
        pts = [(0, 28), (9, 22), (17, 25), (26, 15), (35, 18), (44, 9), (53, 12), (62, 4)]
        d = "M" + " L".join(f"{x + px:g} {y + py:g}" for px, py in pts)
        out = (f'<path class="mk" d="{d}" {s} pathLength="1" stroke-dasharray="1"/>'
               f'<circle class="md" cx="{x + 62:g}" cy="{y + 4:g}" r="3.2" fill="{accent}"/>')
        if animate:
            css = (f"@keyframes mk{{from{{stroke-dashoffset:1}}}}.mk{{animation:mk 1.1s {EASE} {D0}s backwards}}"
                   f"@keyframes md{{from{{opacity:0;transform:scale(.3)}}}}.md{{transform-box:fill-box;transform-origin:center;"
                   f"animation:md .3s {EASE_IN} {D0 + 1.05:.2f}s backwards}}")
        return out, css
    return "", ""


# ---------------------------------------------------------------- hero
HERO_ROLE = "AI Engineer · LLM Agents · Cloud"
HERO_NAME = "Arya Mahindrakar"
HERO_STATEMENT = "I build AI agents and ship them to production, securely."
HERO_STATUS = "Open to work"
HERO_META = ["AWS Certified Cloud Practitioner", "Pune, India"]
HERO_STAGES = ["plan", "tools", "eval", "deploy"]


def bezier_x_to_progress(p1x, p1y, p2x, p2y, t):
    """CSS cubic-bezier: progress at time fraction t (for syncing nodes with the line)."""
    lo, hi = 0.0, 1.0
    for _ in range(50):
        u = (lo + hi) / 2
        xx = 3 * (1 - u) ** 2 * u * p1x + 3 * (1 - u) * u * u * p2x + u ** 3
        lo, hi = (u, hi) if xx < t else (lo, u)
    u = (lo + hi) / 2
    return 3 * (1 - u) ** 2 * u * p1y + 3 * (1 - u) * u * u * p2y + u ** 3


def time_at_progress(p, curve=(0.4, 0, 0.6, 1)):
    lo, hi = 0.0, 1.0
    for _ in range(50):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if bezier_x_to_progress(*curve, m) < p else (lo, m)
    return (lo + hi) / 2


def hero(theme: str):
    th = THEMES[theme]
    W, PX = COL, 9
    X = 64
    acc = th["fill"] if theme == "light" else th["link"]

    def stacked(col, sz, cls, gid, top0=None, status=True):
        """Stacked layout designed for a `col` px column; sz = real px (eyebrow, name, statement, meta)."""
        k = W / col
        e, nm, st, me = (v * k for v in sz)
        nx = 20 * k
        nmax = W - PX - nx - 12 * k
        while not M.fits(HERO_NAME, nm, 600, "d", W - PX - 6 - (nx - 4)):
            nm -= 1
        st_lines = wrap(HERO_STATEMENT, st, nmax, 600, fam="d", slack=10 * k)
        eye_lines = wrap(HERO_ROLE, e, nmax, 600, fam="d", list_mode=True)
        meta = [HERO_META[0], f"{HERO_META[1]}  ·  {HERO_STATUS}" if status else HERO_META[1]]
        y = (24 * k if top0 is None else top0) + cap(e)
        out = []
        for i, ln in enumerate(eye_lines):
            out.append(line_svg(ln, nx, round(y + i * e * 1.3, 1), round(e, 1), 600, th["fg2"], "d", cls="r r1"))
        y += (len(eye_lines) - 1) * e * 1.3 + 10 * k + cap(nm)
        out.append(line_svg(HERO_NAME, nx - 3, round(y, 1), round(nm, 1), 600, th["fg"], "d", cls="r r2"))
        y += 16 * k + cap(st)
        for i, ln in enumerate(st_lines):
            out.append(line_svg(ln, nx, round(y + i * st * 1.26, 1), round(st, 1), 600, f"url(#{gid})", "d", cls="r r3"))
        y += (len(st_lines) - 1) * st * 1.26 + 16 * k + cap(me)
        for i, ml in enumerate(meta):
            assert M.fits(ml, me, 400, "t", nmax, 10 * k)
            out.append(line_svg(ml, nx, round(y + i * me * 1.35, 1), round(me, 1), 400, th["fg2"], "t", cls="r r4"))
        bottom = y + (len(meta) - 1) * me * 1.35 + me * 0.24 + 22 * k
        gw = max(M.ref(plain([ln]), st, 600, "d") for ln in st_lines)
        return f'<g class="{cls}">{"".join(out)}</g>', bottom, nx, gw

    # phone (column <= 420 px), designed at 308 px; never under 11 px on a 238 px column
    PHONE = (14.5, 32, 17, 14.5)
    assert min(PHONE[0], PHONE[3]) * SMALL_COL / 308 >= MIN_PX
    narrow_svg, n_bottom, nx, nsw = stacked(308, PHONE, "n", "gn")
    # tablet and GitHub's medium layout (421-640 px), designed at 560 px; 11 px or more at 421
    # it keeps the pipeline and the status from the desktop layout above the text
    MID = (17, 54, 26, 17)
    assert min(MID[0], MID[3]) * 421 / 560 >= MIN_PX
    MID_TOP, MID_PIPE = 176, 1.5   # the pipeline is drawn 1.5x so its labels stay legible at 421 px
    mid_svg, m_bottom, mx_, msw = stacked(560, MID, "mid", "gm", top0=MID_TOP)

    # ---- wide layout, bottom-anchored in the panel
    H = max(452, round(n_bottom), round(m_bottom))
    # stacked layouts sit in the optical middle of the panel (slightly above centre)
    def centre(svg, bottom):
        dy = (H - bottom) * 0.42
        return svg if dy < 1 else svg.replace('">', f'" transform="translate(0 {dy:.1f})">', 1)
    narrow_svg = centre(narrow_svg, n_bottom)
    name_sz = next(z for z in range(80, 56, -1) if M.fits(HERO_NAME, z, 600, "d", (W - PX - 8) - (X - 3)))
    room = W - PX - 24 - X
    st_sz = next(z for z in range(32, 22, -1) if M.fits(HERO_STATEMENT, z, 600, "d", room))
    meta_w = "  ·  ".join(HERO_META)
    assert M.fits(HERO_ROLE, 21, 600, "d", room) and M.fits(meta_w, 16, 400, "t", room)
    b_meta = H - 58 - (H - 452) * 0.5
    b_state = b_meta - 46
    b_name = b_state - 52
    b_eye = b_name - 84
    sw = M.ref(HERO_STATEMENT, st_sz, 600, "d")
    wide = [
        line_svg(HERO_ROLE, X, b_eye, 21, 600, th["fg2"], "d", cls="r r1"),
        line_svg(HERO_NAME, X - 3, b_name, name_sz, 600, th["fg"], "d", cls="r r2"),
        line_svg(HERO_STATEMENT, X, b_state, st_sz, 600, "url(#gw)", "d", cls="r r3"),
        line_svg(meta_w, X, b_meta, 16, 400, th["fg2"], "t", cls="r r4"),
    ]
    # agent pipeline (top-left): plan -> tools -> eval -> deploy, filled in sequence once
    py, step = 86, 128
    px = [X + 6 + i * step for i in range(4)]
    FLOW_D, FLOW_T = 0.25, 2.1  # the whole sequence ends at 2.35 s
    pipe = [f'<path d="M{px[0]:g} {py}H{px[-1]:g}" stroke="{th["hair"]}" stroke-width="2" stroke-linecap="round"/>',
            f'<path class="flow" d="M{px[0]:g} {py}H{px[-1]:g}" stroke="{acc}" stroke-width="2" stroke-linecap="round" '
            f'pathLength="1" stroke-dasharray="1" fill="none"/>',
            f'<path class="spark" d="M{px[0]:g} {py}H{px[-1]:g}" stroke="{th["spark"]}" stroke-width="4" stroke-linecap="round" '
            f'pathLength="1" stroke-dasharray=".04 2" fill="none" opacity="0"/>']
    node_css = ""
    for i, (cx, lab) in enumerate(zip(px, HERO_STAGES)):
        pipe.append(f'<circle cx="{cx:g}" cy="{py}" r="8.25" fill="none" stroke="{th["ring"]}" stroke-width="1.5"/>')
        pipe.append(f'<g class="node n{i}"><circle cx="{cx:g}" cy="{py}" r="9" fill="{acc}"/>'
                    f'<path d="M{cx - 4:g} {py + 0.2:g}l2.6 2.6 5-5.2" stroke="{th["hero"] if theme == "dark" else "#fff"}" '
                    f'stroke-width="1.9" fill="none" stroke-linecap="round" stroke-linejoin="round"/></g>')
        pipe.append(line_svg(lab, cx, py + 32, 15, 400, th["fg2"], "m", anchor="middle"))
        t = FLOW_D + FLOW_T * time_at_progress(i / 3) - 0.08
        node_css += f".n{i}{{animation-delay:{max(0.0, t):.2f}s}}"
    st_w = M.ref(HERO_STATUS, 15, 500)
    sx = W - X - st_w
    avail = (f'<circle class="halo" cx="{sx - 14:g}" cy="{py - 5:g}" r="4" fill="{th["green"]}" opacity="0"/>'
             f'<circle cx="{sx - 14:g}" cy="{py - 5:g}" r="4" fill="{th["green"]}"/>'
             + line_svg(HERO_STATUS, sx, py, 15, 500, th["fg"], "t"))
    wide_svg = f'<g class="w">{"".join(pipe)}{avail}{"".join(wide)}</g>'
    tx, ty = mx_ + 18 - MID_PIPE * (X - 3), 58 - MID_PIPE * (py - 9)
    mid_svg = mid_svg.replace('<g class="mid">', f'<g class="mid"><g transform="matrix({MID_PIPE} 0 0 {MID_PIPE} {tx:g} {ty:g})">{"".join(pipe)}</g>', 1)

    g0, g1 = th["grad"]
    defs = (f'<defs><linearGradient id="gw" gradientUnits="userSpaceOnUse" x1="{X:g}" y1="0" x2="{X + sw:g}" y2="0">'
            f'<stop offset="0" stop-color="{g0}"/><stop offset="1" stop-color="{g1}"/></linearGradient>'
            f'<linearGradient id="gn" gradientUnits="userSpaceOnUse" x1="{nx:g}" y1="0" x2="{nx + nsw:g}" y2="0">'
            f'<stop offset="0" stop-color="{g0}"/><stop offset="1" stop-color="{g1}"/></linearGradient>'
            f'<linearGradient id="gm" gradientUnits="userSpaceOnUse" x1="{mx_:g}" y1="0" x2="{mx_ + msw:g}" y2="0">'
            f'<stop offset="0" stop-color="{g0}"/><stop offset="1" stop-color="{g1}"/></linearGradient></defs>')
    PULSE_D, PULSE_T, PULSES = FLOW_D + FLOW_T + 0.05, 0.8, 3   # ends at 4.8 s
    style = (
        ".n,.mid{display:none}@media (max-width:640px){.w{display:none}.mid{display:inline}.panel{rx:40px;ry:40px}}"
        "@media (max-width:420px){.mid{display:none}.n{display:inline}.panel{rx:56px;ry:56px}}"
        # name, role and statement: short fade-and-rise stagger
        + rise("r", 14) + f".r{{animation:r .7s {EASE_IN} backwards}}.r2{{animation-delay:.08s}}.r3{{animation-delay:.16s}}.r4{{animation-delay:.24s}}"
        # the progress line draws once; a highlight travels just ahead of it; nodes fill as it passes
        + f"@keyframes flow{{from{{stroke-dashoffset:1}}}}.flow{{animation:flow {FLOW_T}s {EASE} {FLOW_D}s backwards}}"
        + f"@keyframes spark{{0%{{stroke-dashoffset:.02;opacity:0}}6%{{opacity:1}}88%{{opacity:1}}100%{{stroke-dashoffset:-.98;opacity:0}}}}"
        + f".spark{{animation:spark {FLOW_T}s {EASE} {FLOW_D}s backwards}}"
        + f"@keyframes pop{{from{{opacity:0;transform:scale(.4)}}}}"
        + f".node{{transform-box:fill-box;transform-origin:center;animation:pop .32s {EASE_IN} backwards}}" + node_css
        # then the availability dot pulses gently and rests
        + f"@keyframes halo{{0%{{opacity:.5;transform:scale(1)}}100%{{opacity:0;transform:scale(2.8)}}}}"
        + f".halo{{transform-box:fill-box;transform-origin:center;animation:halo {PULSE_T}s {EASE} {PULSE_D:.2f}s {PULSES}}}"
    )
    assert PULSE_D + PULSE_T * PULSES < 5
    panel = f'<rect class="panel" x="{PX}" y="0" width="{W - 2 * PX}" height="{H}" rx="28" fill="{th["hero"]}"/>'
    alt = (f"{HERO_NAME}, {speech(HERO_ROLE)}. {HERO_STATEMENT} {HERO_STATUS}. "
           f"{HERO_META[0]}. {HERO_META[1]}.")
    return svg_doc(W, H, alt, defs + panel + wide_svg + mid_svg + narrow_svg, style), alt


# ---------------------------------------------------------------- headlines
def headline(theme: str, text: str, eyebrow: str | None = None, sub: str | None = None,
             size: float = 48, gradient: bool = False, ident: str = "h",
             lines_w: list[str] | None = None, top_air: float = 120):
    """Centred section headline, 846 units wide, with a phone layout (<= 640 px).

    Bottom-anchored, so `top_air` is section rhythm above it on desktop. The phone
    headline is the largest size (26 px down to 21 px real at 308) that keeps the phone
    layout within the desktop height."""
    th = THEMES[theme]
    W = COL
    X = W / 2
    maxw = W - 2 * 24
    k = W / 308
    E_W, S_W = 19, 21
    E_M, S_M = 23, 23              # 421-640 px columns: 11 px or more at 421
    E_N, S_N = 14.5 * k, 14.5 * k  # <= 420 px columns: 11 px or more at 238

    wl = ([[(w, False) for w in ln.split(" ")] for ln in lines_w] if lines_w
          else wrap(text, size, maxw, 600, fam="d"))
    while not all(M.fits(plain([l]), size, 600, "d", maxw) for l in wl):
        size -= 1

    def stack(hs, n_lines, es, ss, n_sub, ehs=1):
        y, marks = 0.0, {}
        if eyebrow:
            y += cap(es)
            marks["e"] = y
            y += es * 0.55 + cap(hs) + es * 0.4
        else:
            y += cap(hs)
        marks["h"] = [y + i * hs * 1.1 for i in range(n_lines)]
        y = marks["h"][-1]
        if sub:
            y += ss * 0.85 + cap(ss)
            marks["s"] = [y + i * ss * 1.3 for i in range(n_sub)]
            y = marks["s"][-1]
        return marks, y + (ss if sub else hs) * 0.26

    w_marks, w_h = stack(size, len(wl), E_W, S_W, 1)
    m_marks, m_h = stack(size, len(wl), E_M, S_M, 1)
    H = round(max(w_h, m_h) + top_air)
    sub_n = wrap(sub, S_N, maxw, 400, list_mode=True) if sub else []

    def narrow_at(real):
        ns = real * k * (1.08 if gradient else 1)
        lines = wrap(text, ns, maxw, 600, fam="d")
        if lines_w and all(M.fits(l, ns, 600, "d", maxw) for l in lines_w):
            lines = wl
        return (ns, lines, *stack(ns, len(lines), E_N, S_N, len(sub_n)))

    for real in [26, 25, 24, 23, 22, 21]:
        nsize, nl, n_marks, n_h = narrow_at(real)
        if n_h + 8 * k <= H:
            break
    else:
        nsize, nl, n_marks, n_h = narrow_at(22)
    H = round(max(H, n_h + 8 * k))

    def grad(gid, lines, s):
        if not gradient:
            return ""
        g0, g1 = th["grad"]
        ww = max(M.ref(plain([l]), s, 600, "d") for l in lines)
        return (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{X - ww / 2:g}" y1="0" x2="{X + ww / 2:g}" y2="0">'
                f'<stop offset="0" stop-color="{g0}"/><stop offset="1" stop-color="{g1}"/></linearGradient>')

    def render(marks, total, lines, hs, es, ss, sub_lines, cls, gid):
        off = H - total - 3
        out = []
        if eyebrow:
            out.append(line_svg(eyebrow, X, round(marks["e"] + off, 1), round(es, 2), 600, th["fg2"], "d", anchor="middle"))
        fill = f"url(#{gid})" if gradient else th["fg"]
        for yy, ln in zip(marks["h"], lines):
            out.append(line_svg(ln, X, round(yy + off, 1), round(hs, 2), 600, fill, "d", anchor="middle"))
        if sub:
            for yy, ln in zip(marks["s"], sub_lines):
                out.append(line_svg(ln, X, round(yy + off, 1), round(ss, 2), 400, th["fg2"], "t", anchor="middle"))
        return f'<g class="{cls}">{"".join(out)}</g>'

    defs = f"<defs>{grad('gw', wl, size)}{grad('gn', nl, nsize)}</defs>" if gradient else ""
    body = (defs + render(w_marks, w_h, wl, size, E_W, S_W, [[(sub, False)]] if sub else [], "w", "gw")
            + render(m_marks, m_h, wl, size, E_M, S_M, [[(sub, False)]] if sub else [], "mid", "gw")
            + render(n_marks, n_h, nl, nsize, E_N, S_N, sub_n, "n", "gn"))
    style = (".n,.mid{display:none}@media (max-width:640px){.w{display:none}.mid{display:inline}}"
             "@media (max-width:420px){.mid{display:none}.n{display:inline}}")
    alt = ": ".join(x for x in [eyebrow, speech(text) + (f" {speech(sub)}" if sub else "")] if x)
    if sub:
        alt = (f"{eyebrow}: " if eyebrow else "") + text.rstrip(".") + ": " + speech(sub) + "."
    return svg_doc(W, H, alt, body, style, ident), alt


# ---------------------------------------------------------------- tiles
@dataclass
class Tile:
    top: object                # callable(mode, scale) -> list[Block]
    bottom: object = None      # callable(mode, scale) -> list[Block], bottom-anchored
    motif: str | None = None
    accent: tuple | None = None
    alt: str = ""
    ident: str = "t"
    art: object = None         # callable(theme, mode, x, y, w, scale) -> (svg, css, height): custom artwork under the text
    motif_row: bool = False    # lay the eyebrow out as if a motif sat beside it (aligns with motif tiles)
    _h: dict = field(default_factory=dict)


PHONE_SCALES = [1.08, 1.04, 1.0]
WIDE_SCALES = [1.16, 1.12, 1.08, 1.04, 1.0]


def tile_layout(t: Tile, W, mode, s, pad, th2, theme, H=None, animate=False):
    """Lay out one tile. Returns (svg, css, need) where need is the height the content needs."""
    INS = 6
    cw = W - 2 * INS
    x0 = INS + pad
    maxw = cw - 2 * pad
    slack = pad - 8  # DejaVu may use the padding but stays 8 units clear of the card edge
    css = ""
    out = ""
    top = pad
    if t.motif or t.motif_row:
        mx, my = W - INS - pad - 64, pad - 4
        if t.motif:
            m, css = motif(t.motif, mx, my, th2["acc"], th2, animate)
            out += m
        blocks = t.top(mode, s)
        eb = blocks[0]
        # the eyebrow sits on the motif's centre line; the title clears the motif
        e_svg, e_bot = layout_blocks([eb], x0, my + 18 - cap(eb.size) / 2, maxw - 72, th2, 0)
        out += e_svg
        rest_top = max(my + 36 + 10, e_bot + 10)
        r_svg, y = layout_blocks(blocks[1:], x0, rest_top, maxw, th2, slack)
        out += r_svg
    else:
        r_svg, y = layout_blocks(t.top(mode, s), x0, top, maxw, th2, slack)
        out += r_svg
    if t.art:
        a_svg, a_css, a_h = t.art(theme, mode, x0, y + 18 * s, maxw, s)
        out += a_svg
        css += a_css
        y += 18 * s + a_h
    need = y + pad
    if t.bottom:
        bl = t.bottom(mode, s)
        _, bh = layout_blocks(bl, 0, 0, maxw, th2, slack)
        need = y + 22 * s + bh + pad
        if H is not None:
            b_svg, _ = layout_blocks(bl, x0, H - INS - pad - bh, maxw, th2, slack)
            out += b_svg
    return out, css, need + INS


def tile_svgs(tiles: list[Tile], W: int, theme: str, pad_w: float, pad_n: float | None = None,
              radius: float = 20, eq: int = 1, phone: bool = False, enter: bool = True, grow: bool = True):
    """Render tiles. Tiles in each run of `eq` share one height (chosen so rows line up in
    every flow). The desktop layout sets that height; the phone layout takes the largest
    scale that fits it. Returns [(svg, alt)]."""
    th = THEMES[theme]
    INS = 6
    cw = W - 2 * INS
    ths = []
    for t in tiles:
        acc = t.accent[0 if theme == "light" else 1] if t.accent else None
        ths.append(dict(th, acc=acc or th["link"]))
    def need(i, mode, sc):
        return tile_layout(tiles[i], W, mode, sc, pad_w if mode == "w" else pad_n, ths[i], theme)[2]

    # a run's height: the larger of the desktop layout at its base size and the phone layout at its floor
    base = [max(need(i, "w", 1.0), need(i, "n", PHONE_SCALES[-1]) if phone else 0) for i in range(len(tiles))]
    heights = []
    for r0 in range(0, len(tiles), eq):
        heights += [round(max(base[r0:r0 + eq]))] * len(tiles[r0:r0 + eq])
    # one type scale per group and layout: the largest that every tile fits, so type stays consistent
    wide_scales = WIDE_SCALES if (phone and grow) else [1.0]
    sw_ = next((sc for sc in wide_scales if all(need(i, "w", sc) <= heights[i] for i in range(len(tiles)))), 1.0)
    sn_ = next((sc for sc in PHONE_SCALES if all(need(i, "n", sc) <= heights[i] for i in range(len(tiles)))),
               PHONE_SCALES[-1]) if phone else 1.0
    results = []
    for i, (t, H) in enumerate(zip(tiles, heights)):
        card = (f'<rect class="card" x="{INS}" y="0" width="{cw}" height="{H - INS}" rx="{radius}" '
                f'fill="{th["tile"]}" fill-opacity="{th["tile_op"]}"'
                + (f' stroke="{th["stroke"]}" stroke-opacity=".09" stroke-width="1"' if th["stroke"] != "none" else "") + "/>")
        sw, css_w, _ = tile_layout(t, W, "w", sw_, pad_w, ths[i], theme, H, animate=True)
        style = css_w
        if phone:
            sn, css_n, _ = tile_layout(t, W, "n", sn_, pad_n, ths[i], theme, H, animate=True)
            content = f'<g class="w">{sw}</g><g class="n">{sn}</g>'
            bp = 640 if W >= COL else W - 21
            style += f".n{{display:none}}@media (max-width:{bp}px){{.w{{display:none}}.n{{display:inline}}}}"
            if css_n != css_w:
                style += css_n
        else:
            content = sw
        if enter:  # one-time entrance: fade plus a 12 px rise, staggered across the row
            delay = (i % (COL // W)) * 0.08
            body = f'<g class="e">{card}{content}</g>'
            style = rise("e", 12) + f".e{{animation:e .6s {EASE_IN} {delay:.2f}s backwards}}" + style
        else:
            body = card + content
        results.append((svg_doc(W, H, t.alt, body, style, t.ident), t.alt))
    return results


# ---------------------------------------------------------------- stats with a count-up
def count_values(final: str, n: int = 8) -> list[str]:
    """Values a counter passes through on its way to `final`, in the same format."""
    m = re.search(r"\d+(?:\.\d+)?", final)
    num = float(m.group())
    dec = len(m.group().split(".")[1]) if "." in m.group() else 0
    pre, post = final[:m.start()], final[m.end():]
    post_mid = post.replace("+", "")  # "10+ hrs" counts as "4 hrs", lands on "10+ hrs"
    vals = []
    for i in range(n - 1):
        v = num * i / (n - 1)
        vals.append(f"{pre}{v:.{dec}f}{post_mid}")
    return vals + [final]


def stat_pair(stats, theme: str, H: int | None = None, base_delay: float = 0.0, ident: str = "s"):
    """One 420-unit image holding two stat cards. With H=None returns the height needed."""
    th = THEMES[theme]
    W, INS, GUT = 420, 6, 12
    cw = (W - 2 * INS - GUT) / 2
    floor = MIN_PX * W / SMALL_COL  # 19.4 units
    layouts = {"w": dict(num=46, lab=17, lab_lh=22, det=15, det_lh=20, pad=22),
               "n": dict(num=50, lab=floor, lab_lh=floor * 1.22, det=floor, det_lh=floor * 1.22, pad=16)}
    rendered, need, css = {}, 0.0, ""
    for mode, L in layouts.items():
        parts = []
        for j, (num, lab, det) in enumerate(stats):
            x0 = INS + j * (cw + GUT) + L["pad"]
            maxw = cw - 2 * L["pad"]
            ns = L["num"]
            probe = re.sub(r"\d", "0", num)  # tabular figures: every digit as wide as the widest
            while not M.fits(probe, ns, 600, "d", maxw, L["pad"] - 6):
                ns -= 1
            top = L["pad"] + 4
            base = top + cap(ns)
            # labels: bottom-anchored when the card is taller than its content
            bl = [Block(lab, L["lab"], L["lab_lh"], 600, "fg"),
                  Block(det, L["det"], L["det_lh"], 400, "fg2", gap=L["det"] * 0.42)]
            _, bh = layout_blocks(bl, 0, 0, maxw, th, L["pad"] * 0.6)
            need = max(need, base + ns * 0.24 + ns * 0.3 + bh + L["pad"] + INS)
            if H is None:
                continue
            y_lab = max(base + ns * 0.24 + ns * 0.3, H - INS - L["pad"] - bh)
            lsvg, _ = layout_blocks(bl, x0, y_lab, maxw, th, L["pad"] * 0.6)
            # count-up: a strip of values rolls up behind a clip window and stops on the final value
            vals = count_values(num)
            LH = ns * 1.25
            cid = f"c{mode}{j}"
            strip = "".join(line_svg(v, x0, round(base + (len(vals) - 1 - q) * LH, 1), ns, 600, th["fg"], "d",
                                     extra='style="font-variant-numeric:tabular-nums"')
                            for q, v in enumerate(vals))
            dist = round((len(vals) - 1) * LH, 1)
            parts.append(f'<clipPath id="{cid}"><rect x="{INS + j * (cw + GUT):g}" y="{base - ns * 0.86:.1f}" width="{cw:g}" height="{ns * 1.12:.1f}"/></clipPath>'
                         f'<g clip-path="url(#{cid})"><g class="o o{mode}{j}">{strip}</g></g>{lsvg}')
            css += (f"@keyframes o{mode}{j}{{from{{transform:translateY(-{dist}px)}}}}"
                    f".o{mode}{j}{{animation:o{mode}{j} 1.2s {EASE_IN} {base_delay + j * 0.12:.2f}s backwards}}")
        rendered[mode] = "".join(parts)
    if H is None:
        return round(need)
    cards = "".join(f'<rect x="{INS + j * (cw + GUT):g}" y="0" width="{cw:g}" height="{H - INS}" rx="20" '
                    f'fill="{th["tile"]}" fill-opacity="{th["tile_op"]}"'
                    + (f' stroke="{th["stroke"]}" stroke-opacity=".09"' if th["stroke"] != "none" else "") + "/>"
                    for j in range(2))
    body = cards + f'<g class="w">{rendered["w"]}</g><g class="n">{rendered["n"]}</g>'
    style = ".n{display:none}@media (max-width:399px){.w{display:none}.n{display:inline}}" + css
    alt = " ".join(f"{lab}: {speech(num)}, {speech(det)}." for num, lab, det in stats)
    return svg_doc(W, H, alt, body, style, ident), alt


# ---------------------------------------------------------------- pills
def pill(label: str, theme: str, filled: bool, side: str):
    """Apple-style pill button, 44 units tall. `side` adds a 6-unit gutter on that side."""
    th = THEMES[theme]
    size = 17
    tw = M.width(label, size, 400)[0]
    pw = round(tw + 44)
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
REPOS = [  # fallback copies; build() refreshes desc and lang from GitHub
    dict(key="autoswe", slug="Autonomous-AI-Software-Engineering-Platform", name="AutoSWE", lang="Python", flagship=True,
         desc="AutoSWE: multi-agent LLM platform (Claude) that turns a plain-English spec into a validated, deployable project: FastAPI code, tests, Dockerfile, CI, Kubernetes and Terraform. Live agent progress UI, offline mode, 150+ tests."),
    dict(key="securecart", slug="SecureCart-Cloud-Native-Security-Enhanced-eCommerce-Platform", name="SecureCart", lang="TypeScript",
         desc="Security-focused full-stack e-commerce platform: Django REST + React/TypeScript. Rotating httpOnly refresh tokens, RBAC, oversell-proof transactional checkout, audit log, strict CSP. 252 tests incl. Playwright + axe e2e, Dockerized, CI."),
    dict(key="microservices", slug="secure-cloud-microservices-platform", name="Secure Cloud Microservices Platform", lang="Python",
         desc="Secure cloud-native microservices: Python (Django) auth service issuing JWTs via JWKS + Java 21 Spring Boot orders service, behind a Traefik gateway, with Prometheus/Grafana, Kubernetes manifests, GitHub Actions + Jenkins CI/CD, Trivy scans and a 28-test e2e suite."),
    dict(key="multitenant", slug="secure-multi-tenant-platform", name="Secure Multi-Tenant Platform", lang="Python",
         desc="Multi-tenant SaaS backend (Django REST Framework): fail-closed tenant isolation, RBAC, expiring invitations, hardened JWT, strict CSP and an append-only audit log, with a 247-test suite that proves cross-tenant isolation."),
    dict(key="momentum", slug="Momentum-Live-Stock-Tracker", name="Momentum Live Stock Tracker", lang="Python",
         desc="Apple Stocks-style Streamlit dashboard for global stocks, indices, FX and crypto: area and candlestick charts, tested technical indicators (SMA/EMA/RSI/MACD/Bollinger), comparison and a watchlist rail. 250 tests, 95% coverage, typed, Dockerized."),
]

# AutoSWE's five agents, as named in its pipeline (src/autoswe/pipeline/agents.py)
AUTOSWE_AGENTS = ["Analyst", "Architect", "Coder", "DevOps", "Reviewer"]

STATS = [
    ("99.9%", "Uptime at $0 hosting cost", "EcoQuest"),
    ("↓ 90%", "Deployment downtime", "20 min → under 2 min on EC2"),
    ("↓ 40%", "Database read latency", "MongoDB indexing + caching"),
    ("10+ hrs", "Saved every week", "Airflow ETL automation"),
]

# What I do: AI first. Each AI tile is backed by code (see the commit message for sources).
CAPS = [
    ("Extend with AI", "Claude AI",
     "Claude-powered personalization with safety filtering, plus GenAI and RAG fundamentals"),
    ("Multi-agent orchestration", "Claude · FastAPI · AutoSWE",
     "A **five-agent LLM pipeline** (analyst → architect → coder → DevOps → reviewer) with output validation and an automatic repair pass"),
    ("Tool calling, MCP & RAG", "MCP · Ollama · OpenAI-compatible APIs",
     "Tool-calling agents, **MCP tools**, embeddings and semantic search, and persistent agent memory"),
    ("LLM evals & testing", "pytest · GitHub Actions",
     "**Scheduled LLM answer evals in CI**, and deterministic offline providers that make agent pipelines testable without API keys"),
    ("Guardrails", "Claude AI · AutoSWE",
     "Safety filtering on Claude-powered personalization, plus **parsing and policy checks on every generated file**"),
    ("Secure & Observe", "Grafana · Wazuh",
     "JWT, RBAC, rate limiting and IAM policies, plus Grafana alerting and Wazuh SIEM"),
    ("Build", "Django · Node.js · React",
     "Full-stack apps, REST APIs and real-time WebSocket engines handling **50+ live sessions**"),
    ("Ship", "Jenkins · GitHub Actions · Docker",
     "CI/CD pipelines and zero-downtime releases that cut deploy downtime **from 20 min to under 2**"),
    ("Run", "AWS · Linux · Bash",
     "AWS EC2, S3, IAM, VPC and RDS, with Linux process management and Bash automation"),
    ("Automate", "PostgreSQL · MongoDB · Go",
     "Airflow ETL pipelines and Go ingestion services that **save 10+ hours a week**"),
]

STACK = [
    ("AI agents & LLMs", "Multi-agent pipelines · MCP · tool calling",
     "Anthropic & OpenAI-compatible APIs · Ollama · embeddings & semantic search · agent memory · LLM evals"),
    ("AI / ML", "Claude AI · Generative AI · RAG", "Supervised & unsupervised learning · model evaluation metrics"),
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


def refresh_repos():
    """Use the live GitHub description and language; keep the stored copy if offline."""
    for r in REPOS:
        live = None
        try:
            out = subprocess.run(["gh", "repo", "view", f"{GH_USER}/{r['slug']}", "--json", "description,primaryLanguage"],
                                 capture_output=True, text=True, timeout=30, encoding="utf-8")
            if out.returncode == 0:
                live = json.loads(out.stdout)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if live is None:
            try:
                with urllib.request.urlopen(f"https://api.github.com/repos/{GH_USER}/{r['slug']}", timeout=20) as resp:  # noqa: S310
                    d = json.loads(resp.read())
                live = {"description": d.get("description"), "primaryLanguage": {"name": d.get("language")}}
            except OSError:
                print(f"note: {r['slug']}: GitHub unreachable, using the stored description")
                continue
        desc, lang = live.get("description"), (live.get("primaryLanguage") or {}).get("name")
        if desc and desc != r["desc"]:
            print(f"note: {r['slug']}: description changed on GitHub; using the live text (update REPOS to match)")
            r["desc"] = desc
        if lang and lang != r["lang"]:
            r["lang"] = lang


# ---------------------------------------------------------------- README assembly
def write(name: str, svgs: dict[str, str]):
    for theme, s in svgs.items():
        (ASSETS / f"{name}-{theme}.svg").write_text(s, encoding="utf-8", newline="\n")


def pic(name: str, width: str, alt: str) -> str:
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="assets/{name}-dark.svg">'
            f'<img src="assets/{name}-light.svg" width="{width}" alt="{esc(alt)}"></picture>')


def group(prefix, tiles, W, pad_w, pad_n=None, radius=20, links=None, names=None, eq=1, phone=False):
    by_theme = {t: tile_svgs(tiles, W, t, pad_w, pad_n, radius, eq, phone) for t in THEMES}
    items = []
    for i in range(len(tiles)):
        nm = f"{prefix}-{names[i] if names else i + 1}"
        write(nm, {t: by_theme[t][i][0] for t in THEMES})
        p = pic(nm, str(W), by_theme["light"][i][1])
        items.append(f'<a href="{links[i]}">{p}</a>' if links and links[i] else p)
    return f'<p align="center">{"".join(items)}</p>'


def autoswe_art(theme, mode, x, y, w, s):
    """AutoSWE's five agents in order, each lighting as the work passes. Returns (svg, css, height)."""
    th = THEMES[theme]
    acc = REPO_ACCENT["autoswe"][0 if theme == "light" else 1]
    lab = 13.5 * s if mode == "w" else 19.5 * s
    r = 7 * s if mode == "w" else 9 * s
    lw = [M.width(nm, lab, 500)[1] for nm in AUTOSWE_AGENTS]  # widest face, so names never touch
    c0 = x + max(r, lw[0] / 2)
    c4 = x + w - max(r, lw[-1] / 2)
    gap = (c4 - c0) / 4
    cy = y + r + 2
    # on phones the five names do not fit one line: alternate them over two lines
    rows = [[0, 1, 2, 3, 4]] if mode == "w" and all(
        (lw[i] + lw[i + 1]) / 2 + 8 <= gap for i in range(4)) else [[0, 2, 4], [1, 3]]
    out = [f'<path d="M{c0:g} {cy:g}H{c4:g}" stroke="{th["hair"]}" stroke-width="2" stroke-linecap="round"/>']
    for i in range(5):
        cx = c0 + i * gap
        out.append(f'<circle cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="{acc}"/>')
        out.append(f'<circle class="ag ag{i}" cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="none" stroke="{acc}" stroke-width="2" opacity="0"/>')
    ty = cy + r + 8 + cap(lab)
    for row, idx in enumerate(rows):
        for i in idx:
            out.append(line_svg(AUTOSWE_AGENTS[i], c0 + i * gap, round(ty + row * lab * 1.3, 1), round(lab, 2), 500,
                                th["fg2"], "t", anchor="middle"))
    css = (f"@keyframes ag{{0%{{opacity:.9;transform:scale(1)}}100%{{opacity:0;transform:scale(2.2)}}}}"
           f".ag{{transform-box:fill-box;transform-origin:center;animation:ag .7s {EASE} .8s backwards}}"
           + "".join(f".ag{i}{{animation-delay:{0.8 + i * 0.22:.2f}s}}" for i in range(5)))
    h = 2 * r + 2 + 8 + cap(lab) + lab * 0.3 + (len(rows) - 1) * lab * 1.3
    return "".join(out), css, h


def build():
    ASSETS.mkdir(exist_ok=True)
    for f in ASSETS.glob("*.svg"):
        f.unlink()
    refresh_repos()
    md = []

    # hero
    out = {t: hero(t) for t in THEMES}
    write("hero", {t: v[0] for t, v in out.items()})
    md.append(f'<p align="center">{pic("hero", str(COL), out["light"][1])}</p>')

    e = {t: pill("Email me", t, True, "right") for t in THEMES}
    r = {t: pill("Browse my repos", t, False, "left") for t in THEMES}
    write("cta-email", {t: v[0] for t, v in e.items()})
    write("cta-repos", {t: v[0] for t, v in r.items()})
    cta = (f'<p align="center"><a href="mailto:{EMAIL}">{pic("cta-email", str(e["light"][2]), "Email me")}</a>'
           f'<a href="{GH}?tab=repositories">{pic("cta-repos", str(r["light"][2]), "Browse my repos")}</a></p>')
    md.append(cta)

    def head(name, text, tag="h2", **kw):
        o = {t: headline(t, text, ident=name.replace("-", ""), **kw) for t in THEMES}
        write(name, {t: v[0] for t, v in o.items()})
        p = pic(name, str(COL), o["light"][1])
        return f'<{tag} align="center">{p}</{tag}>' if tag else f'<p align="center">{p}</p>'

    # about
    md.append("<!-- About -->")
    md.append(head("h-about", "I turn code into reliable, secure production systems.", eyebrow="About me", size=56,
                   lines_w=["I turn code into reliable,", "secure production systems."]))
    md.append("<p align=\"center\">I work across the whole path to production: I write the backend, build the pipeline that ships it, "
              "run it on AWS, and set up the monitoring and security that keep it healthy. "
              "Then I measure the result and make it faster.</p>")

    # what I do: AI first
    md.append(head("h-what", "What I do.", tag="h3", sub="AI Integrations · DevOps · Cloud · Security"))
    floor = MIN_PX * 420 / SMALL_COL
    tiles = []
    for i, (title, tech, text) in enumerate(CAPS):
        def top(mode, s, title=title, tech=tech, text=text):
            if mode == "w":
                return [Block(tech, 13.5 * s, 18 * s, 600, "fg2", list_mode=True),
                        Block(title, 24 * s, 29 * s, 600, "fg", gap=10 * s, fam="d"),
                        Block(text, 16 * s, 22.5 * s, 400, "fg2", gap=9 * s, bold_color="fg")]
            return [Block(tech, floor * s, floor * s * 1.25, 600, "fg2", list_mode=True),
                    Block(title, 30 * s, 35 * s, 600, "fg", gap=10 * s, fam="d"),
                    Block(text, floor * s, floor * s * 1.32, 400, "fg2", gap=10 * s, bold_color="fg")]
        tiles.append(Tile(top, alt=f"{title}: {speech(text)}. {speech(tech)}.", ident=f"c{i}"))
    md.append(group("cap", tiles, 420, pad_w=28, pad_n=24, radius=24, eq=2, phone=True))

    # impact
    md.append("<!-- Impact -->")
    md.append(head("h-impact", "Impact at a glance."))
    chunks = [STATS[:2], STATS[2:]]
    sh = max(stat_pair(c, t) for c in chunks for t in THEMES)
    pairs = []
    for i, chunk in enumerate(chunks):
        o = {t: stat_pair(chunk, t, sh, base_delay=0.15 + i * 0.24, ident=f"s{i}") for t in THEMES}
        write(f"impact-{i + 1}", {t: v[0] for t, v in o.items()})
        pairs.append(pic(f"impact-{i + 1}", "420", o["light"][1]))
    md.append(f'<p align="center">{"".join(pairs)}</p>')

    # stack: AI first
    md.append("<!-- Tech stack -->")
    md.append(head("h-stack", "Tech stack."))
    tiles = []
    for i, (lab, items, det) in enumerate(STACK):
        def top(mode, s, lab=lab, items=items, det=det):
            bl = [Block(lab, 13, 18, 600, "fg2"), Block(items, 17, 23, 600, "fg", gap=8, list_mode=True)]
            if det:
                bl.append(Block(det, 14, 19, 400, "fg2", gap=8, list_mode=True))
            return bl
        alt = f"{lab}: {speech(items)}" + (f"; {speech(det)}." if det else ".")
        tiles.append(Tile(top, alt=alt, ident=f"k{i}"))
    md.append(group("stack", tiles, 280, pad_w=22, eq=6))

    # repositories: AutoSWE first, as the flagship, beside the shape of its pipeline
    md.append("<!-- Open-source repositories -->")
    md.append(head("h-repos", "Open-source repositories."))
    tiles, links, names = [], [], []
    for r in REPOS:
        def top(mode, s, r=r):
            eb = ("Flagship AI project · " if r.get("flagship") else "") + r["lang"]
            if mode == "w":
                return [Block(eb, 14 * s, 18 * s, 600, "acc"), Block(r["name"], 26 * s, 31 * s, 600, "fg", fam="d"),
                        Block(r["desc"], 16.5 * s, 23.5 * s, 400, "fg2", gap=10 * s)]
            return [Block(eb, floor * s, floor * s * 1.2, 600, "acc"), Block(r["name"], 30 * s, 35 * s, 600, "fg", fam="d"),
                    Block(r["desc"], floor * s, floor * s * 1.32, 400, "fg2", gap=10 * s)]

        def bottom(mode, s):
            return [Block("View on GitHub ›", 16 * s if mode == "w" else floor * s, 20, 400, "link")]
        desc = r["desc"]
        if desc.startswith(r["name"] + ": "):
            desc = desc[len(r["name"]) + 2:]
        alt = f"{r['name']}, {r['lang']} repository on GitHub: {desc}"
        tiles.append(Tile(top, bottom, motif=r["key"], accent=REPO_ACCENT[r["key"]], alt=alt, ident=f"r{r['key']}"))
        links.append(f"{GH}/{r['slug']}")
        names.append(r["key"])
        if r["key"] == "autoswe":
            def a_top(mode, s):
                if mode == "w":
                    return [Block("How AutoSWE works", 14 * s, 18 * s, 600, "acc"),
                            Block("Plain-English spec in. Deployable project out.", 24 * s, 29 * s, 600, "fg", fam="d"),
                            Block("Five agents hand the work along. Every generated file is parsed and policy-checked, "
                                  "with an automatic repair pass.", 16.5 * s, 23.5 * s, 400, "fg2", gap=10 * s)]
                return [Block("How AutoSWE works", floor * s, floor * s * 1.2, 600, "acc"),
                        Block("Plain-English spec in. Deployable project out.", 28 * s, 33 * s, 600, "fg", fam="d"),
                        Block("Five agents hand the work along. Every generated file is parsed and policy-checked, "
                              "with an automatic repair pass.", floor * s, floor * s * 1.32, 400, "fg2", gap=10 * s)]
            alt2 = ("How AutoSWE works: plain-English spec in, deployable project out. Five agents hand the work along: "
                    "analyst, architect, coder, DevOps and reviewer. Every generated file is parsed and policy-checked, "
                    "with an automatic repair pass.")
            tiles.append(Tile(a_top, None, accent=REPO_ACCENT["autoswe"], alt=alt2, ident="rflow", art=autoswe_art,
                              motif_row=True))
            links.append(f"{GH}/{r['slug']}")
            names.append("autoswe-flow")
    md.append(group("repo", tiles, 420, pad_w=30, pad_n=24, radius=24, links=links, names=names, eq=2, phone=True))

    md.append("<!-- Featured projects -->")
    md.append(head("h-projects", "Featured projects."))
    md.append("@@PROJECTS@@")

    # education
    md.append("<!-- Education -->")
    md.append(head("h-edu", "Education & certification."))
    tiles = []
    for i, (eb, title, org, det) in enumerate(EDU):
        def top(mode, s, eb=eb, title=title, org=org, det=det):
            if mode == "w":
                return [Block(eb, 14 * s, 18 * s, 600, "fg2"), Block(title, 24 * s, 29 * s, 600, "fg", gap=10 * s, fam="d"),
                        Block(org, 16 * s, 22 * s, 600, "fg", gap=10 * s, list_mode=True),
                        Block(det, 15 * s, 21 * s, 400, "fg2", gap=12 * s, list_mode=True)]
            return [Block(eb, floor * s, floor * s * 1.2, 600, "fg2"), Block(title, 30 * s, 35 * s, 600, "fg", gap=9 * s, fam="d"),
                    Block(org, floor * s, floor * s * 1.3, 600, "fg", gap=9 * s, list_mode=True),
                    Block(det, floor * s, floor * s * 1.3, 400, "fg2", gap=11 * s, list_mode=True)]
        tiles.append(Tile(top, alt=f"{eb}: {title}. {speech(org)}. {speech(det)}.", ident=f"e{i}"))
    md.append(group("edu", tiles, 420, pad_w=30, pad_n=24, radius=24, names=["degree", "aws"], eq=2, phone=True))

    # motto + contact
    md.append("<!-- Contact -->")
    md.append(head("h-motto", "Secure by design, scalable by default.", tag=None, eyebrow="Motto", size=64, gradient=True,
                   lines_w=["Secure by design,", "scalable by default."]))
    md.append(head("h-contact", "Let’s work together.", top_air=64))
    return md, cta


def main():
    global M
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        M = Measurer(b.new_page())
        md, cta = build()
        b.close()
    template = (ROOT / "scripts" / "README.template.md").read_text(encoding="utf-8")
    parts = "\n\n".join(md)
    head_part, tail_part = parts.split("@@PROJECTS@@")
    out = template.replace("@@TOP@@", head_part.strip()).replace("@@BOTTOM@@", tail_part.strip()).replace("@@CTA@@", cta)
    (ROOT / "README.md").write_text(out, encoding="utf-8", newline="\n")
    print("wrote README.md and", len(list(ASSETS.glob("*.svg"))), "SVGs")


# ---------------------------------------------------------------- validation
def check() -> int:
    """Validate the (optimised) assets and the README's references to them."""
    bad = []
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    refs = set(re.findall(r'(?:src|srcset)="assets/([^"]+)"', readme))
    files = {f.name for f in ASSETS.glob("*.svg")}
    bad += [f"README references missing assets/{r}" for r in sorted(refs - files)]
    bad += [f"unreferenced assets/{f}" for f in sorted(files - refs)]
    for alt in re.findall(r'alt="([^"]*)"', readme):
        if len(alt.strip()) < 3:
            bad.append(f"empty or trivial alt: {alt!r}")
    for f in sorted(ASSETS.glob("*.svg")):
        src = f.read_text(encoding="utf-8")
        try:
            root = ET.fromstring(src)
        except ET.ParseError as e:
            bad.append(f"{f.name}: not well-formed XML: {e}")
            continue
        ns = "{http://www.w3.org/2000/svg}"
        if root.get("role") != "img":
            bad.append(f"{f.name}: missing role=img")
        if not re.fullmatch(r"0 0 [\d.]+ [\d.]+", root.get("viewBox") or ""):
            bad.append(f"{f.name}: missing viewBox")
        t = root.find(f"{ns}title")
        if t is None or not (t.text or "").strip():
            bad.append(f"{f.name}: missing <title>")
        elif root.get("aria-labelledby") != t.get("id"):
            bad.append(f"{f.name}: aria-labelledby does not point at the title")
        css = "".join(s.text or "" for s in root.iter(f"{ns}style"))
        if "prefers-reduced-motion" not in css:
            bad.append(f"{f.name}: no prefers-reduced-motion rule")
        if re.search(r"infinite", css):
            bad.append(f"{f.name}: infinite animation")
        used = set(re.findall(r"animation:([\w-]+)\s", css)) | set(re.findall(r"animation-name:([\w-]+)", css))
        defined = set(re.findall(r"@keyframes\s+([\w-]+)", css))
        if used - defined:
            bad.append(f"{f.name}: animations without keyframes: {sorted(used - defined)}")
        for ref in set(re.findall(r"url\(#([\w-]+)\)", src)):
            if f'id="{ref}"' not in src:
                bad.append(f"{f.name}: url(#{ref}) has no target")
    print("\n".join(bad) if bad else f"OK: {len(files)} SVGs, {len(refs)} references")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    main()
