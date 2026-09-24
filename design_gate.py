#!/usr/bin/env python3
"""Mechanical half of the paper's design merge gate (agreed with Muse, rewritten for the v8 fresh build).
The judgment half stays human. Exit 1 if paper.html breaks any rule a script can check:

  materials : no simulated materials (no feTurbulence noise, no blend-mode textures), no frosted blur, no faux grain,
              and the only image materials are the photographed steel crops
  colour    : orange only on the live pulse and the breaking strip; red only on the breaking pill; no default indigo;
              text/background pairs meet contrast (WCAG): body 7, muted 4.5, chapter numerals 3, brass-on-ink 4.5
  motion    : never `transition: all`; hover styles only inside (hover: hover); a prefers-reduced-motion block exists;
              controls have an :active press state
  structure : reading measure <= 75ch; a named STYLE ANCHOR; the daily photo is credited; the steel photo is credited;
              no display:none nodes shipped in the DOM; no drop cap

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
    """Remove every `@media ... { ... }` block whose header matches opener_regex (brace-matched)."""
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

# ---- materials
check("no simulated materials (noise filters / blend-mode textures)", not re.search(r"feTurbulence|background-blend-mode|--brush", css + js))
check("no active backdrop-filter (frosted glass)", not re.search(r"backdrop-filter\s*:\s*(?!none)", css))
check("no faux grain / wood / paper texture overlays", not re.search(r"\.grain|wood", css) and 'class="grain"' not in html)
imgs = [a or b for a, b in re.findall(r"url\(\s*/static/img/([\w.-]+)\s*\)|url\(\s*img/([\w.-]+)\s*\)", css)]
check("the only image materials are the photographed steel crops", bool(imgs) and all(i.startswith("steel-") for i in imgs), str(imgs))

# ---- the user's hard rules: make your own; nothing borrowed
check("no hazard tape / diagonal stripes (repeating gradients)", not re.search(r"repeating-(linear|conic|radial)-gradient", css))
check("no quotation-mark labels (that motif is banned)", not re.search(r"content\s*:\s*[\"'](\\201[CD]|\u201c|\u201d)", css) and "&ldquo;PLATE" not in js)

# ---- colour
ORANGE = re.compile(r"var\(--hot\)|#ff5c00|#e0622a|rgba\(\s*255\s*,\s*92\s*,\s*0", re.I)
allowed_orange = re.compile(r"^\.live i$|^:root$")
bad = sorted({sel for sel, body in rules if ORANGE.search(body) and not all(allowed_orange.search(x.strip()) for x in sel.split(","))})
check("orange only on the live pulse", not bad, str(bad[:6]))
REDRE = re.compile(r"var\(--red\)|#ed1c24|#f5333a", re.I)
badred = sorted({sel for sel, body in rules if REDRE.search(body) and not re.match(r"^\.pill$|^\.breaking$|^:root$", sel.strip())})
check("red only on the breaking pill and strip", not badred, str(badred[:6]))
check("no default indigo #6366f1", "6366f1" not in html.lower())
paper, ink, brass = tok.get("paper"), tok.get("ink"), tok.get("brass")
low = []
if paper and ink:
    if ratio(ink, paper) < 7: low.append(f"ink/paper {ratio(ink, paper):.1f}")
    if tok.get("mute") and ratio(tok["mute"], paper) < 4.5: low.append(f"mute/paper {ratio(tok['mute'], paper):.1f}")
    for k in ("c1", "c2", "c3", "c4", "c5", "c6"):
        if tok.get(k) and ratio(tok[k], paper) < 3: low.append(f"{k} numeral/paper {ratio(tok[k], paper):.1f}")
if brass and ink and ratio(brass, ink) < 4.5: low.append(f"brass/ink {ratio(brass, ink):.1f}")
check("contrast: body 7+, muted 4.5+, chapter numerals 3+, brass on ink 4.5+", bool(paper and ink) and not low, "; ".join(low))
slab = [f"c{n}" for n in range(1, 7) if tok.get(f"c{n}") and paper and ratio(paper, tok[f"c{n}"]) < 3]
check("paper-coloured chapter titles reach 3:1 on every chapter slab (large text)", not slab, str(slab))
smalltext = [f"ct{n}" for n in range(1, 7) if tok.get(f"ct{n}") and paper and ratio(tok[f"ct{n}"], paper) < 4.5]
check("chapter TEXT colours (--ct1..6) reach 4.5 on paper (numeral colours --c1..6 need 3)", not smalltext and all(tok.get(f"ct{n}") for n in range(1, 7)), str(smalltext))

# ---- motion
check("never `transition: all`", not re.search(r"transition\s*:\s*all\b", css))
check("every :hover style is inside @media (hover: hover)", not re.search(r":hover", strip_blocks(css, r"@media\s*\(hover:\s*hover\)[^{]*")))
check("prefers-reduced-motion is respected", "prefers-reduced-motion" in css)
check("controls have an :active press state", re.search(r"\.btn:active|button:active", css) is not None)

# ---- scrolling safety (a nav highlight once hijacked the page scroll: the nav may only scroll its own strip)
check("the nav never calls scrollIntoView on its links (it hijacks the window scroll)", not re.search(r"\bon\.scrollIntoView|\ba\.scrollIntoView|navLink\.scrollIntoView", js))

# ---- structure
m = re.search(r"\.body p\s*\{[^}]*max-width:\s*(\d+)ch", css)
check("body measure <= 75ch", bool(m) and int(m.group(1)) <= 75, "no .body p max-width")
check("no drop cap", "first-letter" not in css)
check("colophon names a STYLE ANCHOR", "STYLE ANCHOR:" in html)
check("daily photo carries a credit caption", "figcaption" in js and "c.author" in js)
check("steel photograph is credited in the colophon", "Gordeonbleu" in html)
markup = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
used = {c for cl in re.findall(r'class="([^"]+)"', markup) for c in cl.split()}
corpses = sorted(c for c in used if c != "winbar" and any(s.strip() == "." + c and re.search(r"display\s*:\s*none", b) for s, b in rules))
check("no display:none nodes shipped in the DOM (title-bar allowed)", not corpses, str(corpses))

print(f"\n{'GATE PASSED' if not fails else str(fails) + ' RULE(S) BROKEN'}")
sys.exit(1 if fails else 0)
