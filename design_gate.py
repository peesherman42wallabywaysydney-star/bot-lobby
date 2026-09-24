#!/usr/bin/env python3
"""Mechanical half of the design merge gate for v12 (the magazine cover / unbiased reports direction).
The judgment half stays human. Exit 1 if paper.html breaks any rule a script can check:

  banned    : no hazard tape / diagonal stripes (repeating gradients), no quotation-mark labels
  materials : no simulated materials (noise filters, blend-mode textures), no frosted blur, no faux grain,
              and the only image materials are the photographed steel crops
  ground    : the page and body are never a light/white background
  colour    : orange only on the live pulse; red only on breaking; no default indigo; six hue families;
              contrast: cream on ink 7+, cream on every deep ground 7+, cream on every chapter colour 3+ (large text),
              light chapter tones on ink 4.5+, ink on light tones 4.5+, ink on brass 7+
  motion    : never `transition: all`; hover only inside (hover: hover); reduced-motion respected; controls have :active;
              no per-section fade-and-slide reveals; the nav never calls scrollIntoView on its links
  structure : a STYLE ANCHOR; every photograph and the steel are credited in the colophon; no display:none nodes shipped

    python ops/design_gate.py [static/paper.html]
"""
import re
import sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "static" / "paper.html"
html = path.read_text(encoding="utf-8")
css = re.sub(r"/\*.*?\*/", "", "\n".join(re.findall(r"<style>(.*?)</style>", html, re.S)), flags=re.S)
js = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))

fails = 0
def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f"  {detail}" if detail and not ok else ""))
    fails += (not ok)

def strip_blocks(text, opener_regex):
    out, i = [], 0
    pat = re.compile(opener_regex)
    while True:
        m = pat.search(text, i)
        if not m:
            out.append(text[i:]); break
        out.append(text[i:m.start()])
        j = text.index("{", m.start()) + 1; depth = 1
        while depth and j < len(text):
            depth += (text[j] == "{") - (text[j] == "}"); j += 1
        i = j
    return "".join(out)

rules = [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}@][^{}]*)\{([^{}]*)\}", css) if not m.group(1).strip().startswith("@")]

def lum(h):
    h = h.lstrip("#"); r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)
def ratio(a, b):
    la, lb = sorted([lum(a), lum(b)], reverse=True); return (la + .05) / (lb + .05)
tok = {k: v for k, v in re.findall(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})", css)}

# ---- the client's banned list
check("no hazard tape / diagonal stripes (repeating gradients)", not re.search(r"repeating-(linear|conic|radial)-gradient", css))
check("no quotation-mark labels", not re.search(r"content\s*:\s*[\"'](\\201[CD]|“|”)", css) and "&ldquo;PLATE" not in js)

# ---- materials
check("no simulated materials (noise filters / blend-mode textures)", not re.search(r"feTurbulence|background-blend-mode|--brush", css + js))
check("no active backdrop-filter (frosted glass)", not re.search(r"backdrop-filter\s*:\s*(?!none)", css))
check("no faux grain / wood / paper texture overlays", not re.search(r"\.grain|wood", css) and 'class="grain"' not in html)
imgs = [a or b for a, b in re.findall(r"url\(\s*/static/img/([\w.-]+)\s*\)|url\(\s*img/([\w.-]+)\s*\)", css)]
check("the only image materials in CSS are the photographed steel crops", all(i.startswith("steel-") for i in imgs), str(imgs))

# ---- ground: never a light page
def prop_of(sel, prop):
    v = None
    for s_, b in rules:
        if s_.strip() == sel:
            m = re.search(r"(?<![-\w])" + prop + r"\s*:\s*([^;]+)", b)
            if m: v = m.group(1).strip()
    return v
check("the page ground is dark (html and body use --ink)", prop_of("html", "background") == "var(--ink)" and prop_of("body", "background") == "var(--ink)")

# ---- colour
ORANGE = re.compile(r"var\(--hot\)|#ff5c00|#e0622a|rgba\(\s*255\s*,\s*92\s*,\s*0", re.I)
bad = sorted({sel for sel, body in rules if ORANGE.search(body) and not all(re.match(r"^\.live i$|^:root$", x.strip()) for x in sel.split(","))})
check("orange only on the live pulse", not bad, str(bad[:6]))
REDRE = re.compile(r"var\(--red\)|#ed1c24|#f5333a", re.I)
badred = sorted({sel for sel, body in rules if REDRE.search(body) and not re.match(r"^\.pill$|^\.breaking$|^:root$", sel.strip())})
check("red only on the breaking pill and strip", not badred, str(badred[:6]))
check("no default indigo #6366f1", "6366f1" not in html.lower())
check("exactly six hue families (--c1..6, --g1..6, --l1..6)", all(tok.get(f"{p}{n}") for p in "cgl" for n in range(1, 7)) and not tok.get("c7"))
cream, ink, brass = tok.get("cream"), tok.get("ink"), tok.get("brass")
low = []
if cream and ink:
    if ratio(cream, ink) < 7: low.append(f"cream/ink {ratio(cream, ink):.1f}")
    for n in range(1, 7):
        if ratio(cream, tok[f"g{n}"]) < 7: low.append(f"cream/g{n} {ratio(cream, tok[f'g{n}']):.1f}")
        if ratio(cream, tok[f"c{n}"]) < 3: low.append(f"cream/c{n} {ratio(cream, tok[f'c{n}']):.1f} (large text needs 3)")
        if ratio(tok[f"l{n}"], ink) < 4.5: low.append(f"l{n}/ink {ratio(tok[f'l{n}'], ink):.1f}")
        if ratio(ink, tok[f"l{n}"]) < 4.5: low.append(f"ink/l{n} {ratio(ink, tok[f'l{n}']):.1f}")
if brass and ink and ratio(ink, brass) < 7: low.append(f"ink/brass {ratio(ink, brass):.1f}")
check("contrast: cream on ink and deep grounds 7+, on chapter colours 3+, light tones 4.5+, ink on brass 7+", bool(cream and ink) and not low, "; ".join(low))

# ---- motion
check("never `transition: all`", not re.search(r"transition\s*:\s*all\b", css))
check("every :hover style is inside @media (hover: hover)", not re.search(r":hover", strip_blocks(css, r"@media\s*\(hover:\s*hover\)[^{]*")))
check("prefers-reduced-motion is respected", "prefers-reduced-motion" in css)
check("controls have an :active press state", re.search(r"\.btn:active|button:active", css) is not None)
check("no per-section fade-and-slide-up reveals (.rv)", "IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('in')" not in js and not re.search(r"\.rv(?![\w-])", css))
check("the nav never calls scrollIntoView on its links (it hijacks the window scroll)", not re.search(r"\bon\.scrollIntoView|\ba\.scrollIntoView|navLink\.scrollIntoView", js))

# ---- structure
check("colophon names a STYLE ANCHOR", "STYLE ANCHOR:" in html)
check("every photograph is credited in the colophon (title, author, licence)", "creditsList" in js and "credits[k].author" in js and "credits[k].license" in js)
check("the steel photograph is credited in the colophon", "Gordeonbleu" in html)
markup = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
used = {c for cl in re.findall(r'class="([^"]+)"', markup) for c in cl.split()}
corpses = sorted(c for c in used if c != "winbar" and any(s.strip() == "." + c and re.search(r"display\s*:\s*none", b) for s, b in rules))
check("no display:none nodes shipped in the DOM (title-bar allowed)", not corpses, str(corpses))

print(f"\n{'GATE PASSED' if not fails else str(fails) + ' RULE(S) BROKEN'}")
sys.exit(1 if fails else 0)
