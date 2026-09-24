#!/usr/bin/env python3
"""Mechanical half of the paper's design merge gate (agreed with Muse, 2026-09-24). The judgment half stays human.

Fails (exit 1) if paper.html breaks a rule that a script can check:
  no active backdrop-filter | no faux-grain overlay | no default indigo | orange only on controls/alerts |
  body measure <= 75ch | at most ONE heritage device | a named STYLE ANCHOR in the colophon |
  photos carry a credit caption | no more than 6 chapter hues | no giant outlined type

    python ops/design_gate.py [static/paper.html]
"""
import re
import sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "static" / "paper.html"
html = path.read_text(encoding="utf-8")
css = "\n".join(re.findall(r"<style>(.*?)</style>", html, re.S))
js = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

# flatten to (selector, declarations) in source order; @media blocks are flattened (their rules still count)
rules = []
for m in re.finditer(r"([^{}@][^{}]*)\{([^{}]*)\}", css):
    sel, body = m.group(1).strip(), m.group(2)
    if sel.startswith("@") or not sel:
        continue
    rules.append((sel, body))

fails = 0
def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f"  {detail}" if detail and not ok else ""))
    fails += (not ok)

def last_value(selector_regex, prop):
    """Value of `prop` in the LAST rule (source order) whose selector matches - i.e. what actually wins."""
    val = None
    for sel, body in rules:
        if re.search(selector_regex, sel):
            m = re.search(r"(?<![-\w])" + re.escape(prop) + r"\s*:\s*([^;]+)", body)
            if m:
                val = m.group(1).strip()
    return val

# effective declarations: for each (selector, property) the LAST value in source order is what wins
eff = {}
for sel, body in rules:
    for prop, val in re.findall(r"([-\w]+)\s*:\s*([^;]+)", body):
        eff[(sel, prop)] = val.strip()

# 1. frosted blur / faux grain
blur = sorted({sel for (sel, prop), v in eff.items() if prop in ("backdrop-filter", "-webkit-backdrop-filter") and v != "none"})
check("no active backdrop-filter (frosted glass)", not blur, str(blur[:4]))
check("no faux grain overlay (node and rules are gone)", 'class="grain"' not in html and not re.search(r"\.grain\b", css))
check("no wood/paper texture overlay on cards", last_value(r"^\.card::before$", "display") == "none")

# 2. default indigo / violet
check("no default indigo #6366f1", "6366f1" not in html.lower())

# 3. orange is for controls and alerts only - RAW source, so overridden/dead orange fails too
ORANGE = re.compile(r"(?<!var\(--c, )var\(--accent\)|#ff5c00|#e0622a|rgba\(\s*255\s*,\s*92\s*,\s*0", re.I)
CONTROLS = re.compile(r"button|\.btn|select|\.nav a\.on|:hover|:focus|\.bar|\.alert|\.flag|#dateSel|^:root$|^\.hero-live")
offenders = []
for sel, body in rules:
    if ORANGE.search(body.replace("var(--c, var(--accent))", "")) and not CONTROLS.search(sel):
        # the token DEFINITION in :root is allowed; any other use of orange outside controls is not
        if sel.strip() == ":root" and re.fullmatch(r"\s*--accent\s*:\s*#ff5c00\s*;?\s*", body, re.I):
            continue
        offenders.append(sel)
check("orange only on controls / alerts (raw source, dead rules count)", not offenders, str(sorted(set(offenders))[:6]))

# 3b. nothing hidden ships in the DOM: a class used in the markup whose winning rule is display:none is a corpse
markup = re.sub(r"<script>.*?</script>|<style>.*?</style>", "", html, flags=re.S)
used = set(re.findall(r'class="([^"]+)"', markup))
used = {c for cl in used for c in cl.split()}
FUNCTIONAL_HIDDEN = {"winbar"}  # the frameless-window title bar: hidden by default, shown when the desktop widget opens the paper
corpses = sorted(c for c in used if c not in FUNCTIONAL_HIDDEN and last_value(r"^\." + re.escape(c) + r"$", "display") == "none")
check("no display:none nodes shipped in the DOM", not corpses, str(corpses))

# 4. reading measure
m = last_value(r"\.body p", "max-width")
ch = int(re.match(r"(\d+)ch", m).group(1)) if m and re.match(r"\d+ch", m) else None
check("body measure <= 75ch", ch is not None and ch <= 75, f"max-width={m}")

# 5. one heritage device per edition (drop cap, frieze/double-rule, steel frame)
devices = []
if last_value(r"first-letter", "float") not in (None, "none"):
    devices.append("drop cap")
if last_value(r"^\.frieze|\.frieze,", "display") != "none":
    devices.append("frieze")
if re.search(r"\.hero \.frame", css):
    devices.append("steel photo frame")
check("at most one heritage device", len(devices) <= 1, str(devices))

# 6. named style anchor + credited photography
check("colophon names a STYLE ANCHOR", "STYLE ANCHOR:" in html)
check("daily photo carries a credit caption", "figcaption" in js and "c.author" in js)

# 7. hues and type
pal = re.search(r"const PAL = \[(.*?)\]", js)
n = len(re.findall(r"#[0-9a-fA-F]{6}", pal.group(1))) if pal else 99
check("chapter palette has <= 6 hues", n <= 6, f"{n} hues")
check("no giant outlined display letters", not re.search(r"-webkit-text-stroke\s*:\s*[2-9]", css))

print(f"\n{'GATE PASSED' if not fails else str(fails) + ' RULE(S) BROKEN'}")
sys.exit(1 if fails else 0)
