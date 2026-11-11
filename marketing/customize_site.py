#!/usr/bin/env python3
"""Turn the scaffolded skeleton in docs/ into the ADK Lens site.

Rebuild from scratch:
    python3 ~/.claude/skills/new-project-site/scripts/scaffold.py project.json . --force
    python3 marketing/customize_site.py

It adds lens.css / lens.js, swaps the hero image for the animated whiteboard illustration,
puts the rotating coding-agent logos next to the copy button, redraws the four features,
adds the real-screenshot slots (hidden until the files exist) and pairs "open source" with "coffee".
"""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
ICONS = Path.home() / ".claude/skills/new-project-site/templates/agents"
SHEET = json.loads((ROOT / "project.json").read_text(encoding="utf-8"))

T = {
    "en": {
        "prompt": "Plan my weekend", "you": "YOUR PROMPT", "agent": "AGENT", "tool": "TOOL",
        "sticky": ["Why the weather", "first?"],
        "caption": "Illustration of the idea. The real board draws your own agents.",
        "works": "Works with Claude Code, Codex, Antigravity and Gemini CLI, Cursor, GitHub Copilot, Windsurf, or any coding agent.",
        "any": "any agent",
        "board_label": "Illustration: a whiteboard where a prompt travels from one agent to the next, with a sticky note, a circled agent and a version stamp.",
        "shots_title": "The real thing",
        "shots": [
            ("shot-map.png", "ADK Lens screenshot: the map of agents and tools.", "The map of your agents and tools."),
            ("shot-linear.png", "ADK Lens screenshot: the Linear view of a run.", "A run, told in plain words."),
            ("shot-notes.png", "ADK Lens screenshot: notes on the board.", "Your notes, ready to copy as a prompt."),
        ],
    },
    "fr": {
        "prompt": "Prépare mon week-end", "you": "TON PROMPT", "agent": "AGENT", "tool": "OUTIL",
        "sticky": ["Pourquoi la météo", "d'abord ?"],
        "caption": "Illustration de l'idée. Le vrai tableau dessine tes propres agents.",
        "works": "Fonctionne avec Claude Code, Codex, Antigravity et Gemini CLI, Cursor, GitHub Copilot, Windsurf, ou n'importe quel agent de code.",
        "any": "n'importe quel agent",
        "board_label": "Illustration : un tableau blanc où un prompt passe d'un agent à l'autre, avec un post-it, un agent entouré et un tampon de version.",
        "shots_title": "En vrai",
        "shots": [
            ("shot-map.png", "Capture d'ADK Lens : la carte des agents et des outils.", "La carte de tes agents et de tes outils."),
            ("shot-linear.png", "Capture d'ADK Lens : la vue linéaire d'une exécution.", "Une exécution, racontée en mots simples."),
            ("shot-notes.png", "Capture d'ADK Lens : des notes sur le tableau.", "Tes notes, prêtes à copier comme prompt."),
        ],
    },
}


def icon(file: str) -> str:
    svg = (ICONS / file).read_text(encoding="utf-8")
    svg = svg.split("</title>", 1)[-1] if "<title>" in svg else svg.split(">", 1)[1]
    return ('<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true" focusable="false">'
            + svg.replace("</svg>", "").strip() + "</svg>")


def mono(ch: str) -> str:
    return f'<span class="rot__mono">{ch}</span>'


def rotator(lang: str) -> str:
    items = [
        (icon("claude.svg"), "Claude Code"),
        (icon("openai.svg"), "Codex"),
        (icon("googlegemini.svg"), "Antigravity · Gemini CLI"),
        (mono("C"), "Cursor"),
        (icon("githubcopilot.svg"), "GitHub Copilot"),
        (icon("windsurf.svg"), "Windsurf"),
        (mono("+"), T[lang]["any"]),
    ]
    spans = "".join(f'<span class="rot__item">{i}{html.escape(label)}</span>' for i, label in items)
    spans += f'<span class="rot__item rot__item--dup">{items[0][0]}{items[0][1]}</span>'
    return (f'<div class="rot"><div class="rot__list" aria-hidden="true">{spans}</div>'
            f'<span class="sr-only">{html.escape(T[lang]["works"])}</span></div>')


def board_svg(lang: str) -> str:
    t = T[lang]
    e = html.escape
    return f"""<svg viewBox="0 0 840 540" role="img" aria-label="{e(t['board_label'])}">
  <path class="b-line" d="M250 264 L340 264"/>
  <path class="b-line" d="M510 250 C560 250 550 125 600 125"/>
  <path class="b-line" d="M510 280 C560 280 550 405 600 405"/>
  <path class="b-line" d="M700 160 C700 180 720 192 720 212" stroke-dasharray="2 7"/>
  <circle class="b-dot b-dot--a" r="8"/>
  <circle class="b-dot b-dot--b" r="8"/>
  <text class="b-sub" x="44" y="222">{e(t['you'])}</text>
  <g class="b-node b-prompt"><rect x="40" y="232" width="214" height="64" rx="32"/><text x="147" y="270" text-anchor="middle">{e(t['prompt'])}</text></g>
  <text class="b-sub" x="344" y="216">{t['agent']}</text>
  <g class="b-node b-blue"><rect x="340" y="226" width="170" height="76" rx="22"/><rect class="b-ring b-ring--1" x="334" y="220" width="182" height="88" rx="27"/><text x="425" y="271" text-anchor="middle">concierge</text></g>
  <g class="b-node b-green"><rect x="600" y="90" width="200" height="70" rx="22"/><rect class="b-ring b-ring--2" x="594" y="84" width="212" height="82" rx="27"/><text x="700" y="132" text-anchor="middle">weather_agent</text></g>
  <g class="b-node b-tool"><rect x="640" y="212" width="160" height="46" rx="23"/><text x="720" y="240" text-anchor="middle">get_weather</text></g>
  <text class="b-sub" x="630" y="240" text-anchor="end">{t['tool']}</text>
  <g class="b-node b-coral"><rect x="600" y="370" width="170" height="70" rx="22"/><rect class="b-ring b-ring--3" x="594" y="364" width="182" height="82" rx="27"/><text x="685" y="412" text-anchor="middle">planner</text></g>
  <path class="b-circle" d="M588 352 C640 330 760 336 790 384 C812 430 752 468 678 462 C610 458 566 430 572 392 C576 368 600 352 628 346"/>
  <g class="b-q"><circle cx="800" cy="350" r="19"/><text x="800" y="357" text-anchor="middle">?</text></g>
  <g class="b-sticky"><rect x="60" y="380" width="190" height="118" rx="6"/><text x="78" y="428">{e(t['sticky'][0])}</text><text x="78" y="456">{e(t['sticky'][1])}</text></g>
  <g class="b-stamp"><rect x="350" y="418" width="124" height="52" rx="12"/><text x="412" y="451" text-anchor="middle">V2 OK</text></g>
</svg>"""


MINI = [
    # plugs in
    '<svg viewBox="0 0 120 64" aria-hidden="true"><rect class="m-paper" x="2" y="14" width="58" height="36" rx="10"/><text class="m-txt" x="31" y="36" text-anchor="middle">ADK</text>'
    '<g class="m-plug"><rect class="m-blue" x="62" y="14" width="40" height="36" rx="10"/><circle cx="82" cy="32" r="8" fill="none" stroke="#fff" stroke-width="2.5"/></g></svg>',
    # watch, replay
    '<svg viewBox="0 0 120 64" aria-hidden="true"><path class="m-stroke" d="M12 32 H108"/><circle class="m-soft" cx="12" cy="32" r="9"/><circle class="m-soft" cx="60" cy="32" r="9"/><circle class="m-soft" cx="108" cy="32" r="9"/>'
    '<circle class="m-blue m-run" cx="12" cy="32" r="6"/></svg>',
    # circle, comment
    '<svg viewBox="0 0 120 64" aria-hidden="true"><rect class="m-soft" x="14" y="20" width="44" height="24" rx="9"/>'
    '<path class="m-draw" d="M8 22 C22 6 60 8 66 30 C70 50 30 58 12 46 C2 38 6 26 16 20"/><rect class="m-yellow" x="80" y="12" width="34" height="34" rx="3" transform="rotate(5 97 29)"/></svg>',
    # compare
    '<svg viewBox="0 0 120 64" aria-hidden="true"><rect class="m-paper" x="2" y="8" width="52" height="48" rx="10"/><rect class="m-paper" x="66" y="8" width="52" height="48" rx="10"/>'
    '<text class="m-txt" x="10" y="23">V1</text><text class="m-txt" x="74" y="23">V2</text>'
    '<circle class="m-blue" cx="20" cy="40" r="6"/><circle class="m-blue" cx="38" cy="40" r="6"/>'
    '<circle class="m-blue" cx="80" cy="40" r="6"/><circle class="m-blue" cx="94" cy="40" r="6"/><circle class="m-green m-blink" cx="108" cy="40" r="6"/></svg>',
]


def features(lang: str, title: str) -> str:
    lis = "\n".join(
        f'    <li class="feature">{MINI[i]}<h3>{html.escape(f["title"][lang])}</h3><p>{html.escape(f["text"][lang])}</p></li>'
        for i, f in enumerate(SHEET["features"]))
    return f"""<section class="wrap section" id="features" data-reveal aria-labelledby="features-title">
  <h2 class="h2" id="features-title">{title}</h2>
  <ul class="features" role="list">
{lis}
  </ul>
</section>"""


def shots(lang: str, prefix: str) -> str:
    t = T[lang]
    figs = "\n".join(
        f'    <figure class="shot" data-shot="{prefix}assets/{f}" data-alt="{html.escape(alt)}" hidden><figcaption>{html.escape(cap)}</figcaption></figure>'
        for f, alt, cap in t["shots"])
    return f"""<section class="wrap section" id="shots" data-shots hidden aria-labelledby="shots-title">
  <h2 class="h2" id="shots-title">{t['shots_title']}</h2>
  <div class="shots">
{figs}
  </div>
</section>"""


def must(pattern: str, repl, text: str, flags=re.S) -> str:
    out, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        raise SystemExit(f"customize_site: pattern not found: {pattern[:60]}")
    return out


def customize(path: Path, lang: str, prefix: str) -> None:
    s = path.read_text(encoding="utf-8")
    if "lens.css" in s:
        raise SystemExit(f"{path} already customised: re-run scaffold.py --force first")
    s = must(r'(<link rel="stylesheet" href="[^"]*style\.css[^"]*">)',
             lambda m: m.group(1) + f'\n<link rel="stylesheet" href="{prefix}lens.css">', s)
    s = must(r'(<script src="[^"]*site\.js"[^>]*></script>)',
             lambda m: m.group(1) + f'\n<script src="{prefix}lens.js" defer></script>', s)
    # hero: one button + the rotating agents, then the illustration
    s = must(r'<div class="cta">(<button class="btn btn--go.*?</button>).*?</div>\s*\n(\s*<p class="fine">)',
             lambda m: f'<div class="cta">{m.group(1)}{rotator(lang)}</div>\n{m.group(2)}', s)
    s = must(r'<figure class="hero__visual">.*?</figure>',
             lambda m: (f'<figure class="board"><div class="board__frame">{board_svg(lang)}</div>'
                        f'<figcaption>{html.escape(T[lang]["caption"])}</figcaption></figure>'), s)
    # features with their small drawings, then the screenshot slots
    title = re.search(r'id="features-title">(.*?)</h2>', s).group(1)
    s = must(r'<section class="wrap section" id="features".*?</section>',
             lambda m: features(lang, title) + "\n" + shots(lang, prefix), s)
    # agent setup comes after "what it does" (the hero already carries the button)
    agent = re.search(r'<section class="wrap section agent-setup".*?</section>\n', s, re.S).group(0)
    s = s.replace(agent, "", 1)
    s = must(r'(<section class="wrap section panel" id="source")', lambda m: agent + m.group(1), s)
    # open source + coffee side by side
    s = must(r'(<section class="wrap section panel" id="source".*?</section>\s*<section class="wrap section coffee".*?</section>)',
             lambda m: '<div class="wrap duo">\n' + m.group(1) + '\n</div>', s)
    if lang == "fr":  # "ADK Lens" is an "outil": masculine in French
        s = s.replace("Ce qu'elle fait", "Ce que ça fait").replace("est gratuite et le restera", "est gratuit et le restera").replace("Si elle te rend service", "S'il te rend service")
    path.write_text(s, encoding="utf-8")
    print(f"customised {path.relative_to(ROOT)}")


def main() -> int:
    default = SHEET["default_lang"]
    other = "fr" if default == "en" else "en"
    customize(DOCS / "index.html", default, "")
    customize(DOCS / other / "index.html", other, "../")
    return 0


if __name__ == "__main__":
    sys.exit(main())
