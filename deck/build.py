import datetime
import json
from pathlib import Path

ROOT = Path(__file__).parent / "project"
DARK, LIGHT, ACCENT = "#1B2A41", "#F7F5F0", "#C9651F"
BODY_ON_LIGHT, BODY_ON_DARK, LINE = "#4A5568", "#C9D1D9", "#DDD8CF"
HEAD = "'Domine', Georgia, serif"
TEXT = "'IBM Plex Sans', Arial, sans-serif"

slides = []   # (id, html)

def section(sid, inner, bg=LIGHT, color=DARK, notes="", gap=40):
    html = (f'<section id="{sid}" data-transition="fade" style="background:{bg}; color:{color}; '
            f'font-family:{TEXT}; padding:128px 128px 160px; display:flex; flex-direction:column; gap:{gap}px">\n'
            f'{inner}\n'
            f'<p style="position:absolute; left:128px; bottom:64px; font-size:24px; color:{"#8A94A6" if bg == DARK else "#8A8F99"}">Skill evals, the eleven types</p>\n'
            + (f'<aside>{notes}</aside>\n' if notes else '') + '</section>\n')
    slides.append((sid, html))

def eyebrow(text, color=ACCENT):
    return f'<p style="font-size:24px; font-weight:600; letter-spacing:3px; text-transform:uppercase; color:{color}">{text}</p>'

def h2(text, color=DARK):
    return f'<h2 style="font-family:{HEAD}; font-size:72px; font-weight:600; line-height:1.1; color:{color}">{text}</h2>'

def card(title, lines, bg="#FFFFFF", title_color=DARK, body_color=BODY_ON_LIGHT, border=LINE):
    items = "".join(f'<li>{line}</li>' for line in lines)
    return (f'<div style="flex:1; display:flex; flex-direction:column; gap:16px; background:{bg}; '
            f'padding:40px; border:1px solid {border}; border-radius:16px">'
            f'<h3 style="font-size:32px; font-weight:600; color:{title_color}">{title}</h3>'
            f'<ul style="font-size:26px; line-height:1.35; color:{body_color}">{items}</ul></div>')

def type_slide(sid, group, title, question, method, watch, notes):
    inner = "\n".join([
        eyebrow(group),
        h2(title),
        f'<p style="font-size:32px; line-height:1.35; color:{BODY_ON_LIGHT}; width:1500px">{question}</p>',
        '<div style="display:flex; gap:32px">'
        + card("How it works", method)
        + card("Watch out for", watch, bg="#FBF3EC", border="#EAD3C2")
        + '</div>',
    ])
    section(sid, inner, notes=notes, gap=32)


CONTENT = json.loads((Path(__file__).with_name("content.json")).read_text())

for s in CONTENT["slides"]:
    kind = s["kind"]
    if kind in ("cover", "close"):
        heading = (f'<h1 style="font-family:{HEAD}; font-size:120px; font-weight:600; line-height:1.05; color:{LIGHT}">{s["title"]}</h1>'
                   if kind == "cover" else
                   f'<h2 style="font-family:{HEAD}; font-size:72px; font-weight:600; line-height:1.1; color:{LIGHT}">{s["title"]}</h2>')
        section(s["id"], "\n".join([
            '<div style="flex:1"></div>',
            eyebrow(s["eyebrow"], color="#E8A36A"),
            heading,
            f'<p style="font-size:{40 if kind == "cover" else 36}px; line-height:1.3; color:{BODY_ON_DARK}; width:1400px">{s["text"]}</p>',
            '<div style="flex:1"></div>',
        ]), bg=DARK, color=LIGHT, notes=s["notes"])
    elif kind == "cards":
        inner = [eyebrow(s["eyebrow"]), h2(s["title"]),
                 '<div style="display:flex; gap:32px">' + "".join(card(c["title"], c["lines"]) for c in s["cards"]) + '</div>']
        if s.get("footer"):
            inner.append(f'<p style="font-size:28px; color:{BODY_ON_LIGHT}">{s["footer"]}</p>')
        section(s["id"], "\n".join(inner), notes=s["notes"])
    elif kind == "type":
        type_slide(s["id"], s["group"], f'{s["number"]}. {s["title"]}', s["question"], s["method"], s["watch"], s["notes"])
    elif kind == "rules":
        grid = "".join(
            f'<div style="display:flex; gap:20px; background:#FFFFFF; padding:28px 32px; border:1px solid {LINE}; border-radius:16px; align-items:baseline">'
            f'<p style="font-family:{HEAD}; font-size:44px; font-weight:600; color:{ACCENT}">{i}</p>'
            f'<p style="font-size:28px; line-height:1.35; color:{DARK}">{t}</p></div>'
            for i, t in enumerate(s["rules"], start=1))
        section(s["id"], "\n".join([eyebrow(s["eyebrow"]), h2(s["title"]),
                 f'<div style="display:grid; grid-template-columns:repeat(2, 1fr); gap:24px">{grid}</div>']), notes=s["notes"])

for sid, html in slides:
    (ROOT / "slides" / f"{sid}.html").write_text(html)

order = [sid for sid, _ in slides]
deck = {
    "v": 4,
    "createdOnFiles": {"v": 1, "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    "title": CONTENT["title"],
    "order": order,
    "sections": {
        "intro": {"description": "What a skill is and why it needs evaluating", "start": "cover"},
        "static": {"description": "Three checks that cost nothing", "start": "lint"},
        "live": {"description": "Five evals that run the real agent", "start": "trigger"},
        "analysis": {"description": "Three analyses over saved runs", "start": "stats"},
        "wrap": {"description": "The rules and where to start", "start": "rules"},
    },
    "faces": {
        "domine": {"family": "Domine", "href": "https://fonts.googleapis.com/css2?family=Domine:wght@400..700&display=swap"},
        "ibm-plex-sans": {"family": "IBM Plex Sans", "href": "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&display=swap"},
    },
    "designSystems": [],
}
(ROOT / "deck.json").write_text(json.dumps(deck, indent=2))
print(len(order), "slides:", order)
