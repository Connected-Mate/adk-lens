#!/usr/bin/env python3
"""Turn the scaffolded skeleton in docs/ into the ADK Lens site.

Rebuild from scratch:
    python3 ~/.claude/skills/new-project-site/scripts/scaffold.py project.json . --force
    python3 marketing/customize_site.py

The scaffold gives the plumbing (head tags, hreflang, JSON-LD, language redirect, sitemap, 404, manifest).
This script keeps that <head>, writes the whole <body> itself, and swaps the skeleton's style.css / site.js
for the site's own lens.css / lens.js (hand-written, kept in docs/, never generated).
"""
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
ICONS = Path.home() / ".claude/skills/new-project-site/templates/agents"
SHEET = json.loads((ROOT / "project.json").read_text(encoding="utf-8"))
REPO = SHEET["source_repo"]
LEGAL = {"fr": "https://connectedmate.com/fr/mentions-legales/", "en": "https://connectedmate.com/en/legal/"}
e = html.escape

T = {
    "en": {
        "skip": "Skip to content", "home": "home", "nav_label": "Sections", "lang_label": "Version française", "lang_short": "FR",
        "nav": [("#try", "Try it"), ("#features", "What it does"), ("#agent", "Set up"), ("#faq", "Questions")],
        "try_title": "Try it right here", "try_text": "Pick a request and watch it travel through the agents. Nothing to install.",
        "copy": "Copy the setup prompt", "copy_short": "Copy the prompt", "copied": "Prompt copied", "copied_live": "Prompt copied. Paste it into your coding agent.",
        "works": "Works with Claude Code, Codex, Antigravity and Gemini CLI, Cursor, GitHub Copilot, Windsurf, or any coding agent.",
        "any": "any agent",
        "prompt": "Plan my weekend", "you": "YOUR PROMPT", "agent": "AGENTS", "tool": "TOOL",
        "sticky": ["Why the weather", "first?"],
        "board_label": "Illustration: a prompt travels from one agent to the next on a dotted whiteboard, next to one sticky note.",
        "caption": "Site demo, with the agents of the bundled example. The real board draws yours.",
        "statement": "ADK Lens plugs on top of ADK and draws what your agents do, live. Nothing to change in your agent code.",
        "story": ["You ask for a weekend plan.", "concierge hands over to weather_agent.", "weather_agent calls get_weather.", "planner writes the answer."],
        "note": "Why the weather first?", "as_prompt": "Copy as prompt",
        "check": ["The safety check ", "screen_prompt", " stopped the request."], "harder": "Want more to look at? Then run",
        "shots_title": "The real thing", "shots_tabs": "Screenshots",
        "copy_fail": "Your browser blocked the copy.", "copy_fail_link": "Open the setup guide",
        "manual": "No coding agent? Do it by hand", "manual_copy": "Copy the two commands", "manual_copied": "Commands copied", "manual_live": "Commands copied. Paste them into your terminal.",
        "shots": [
            ("shot-map.png", "ADK Lens screenshot: the map of agents and tools, drawn as straight blocks and right-angle arrows.", "The map of your agents and tools, drawn like an architecture diagram.", "The map"),
            ("shot-linear.png", "ADK Lens screenshot: the Story view of a run.", "A run, told in plain words.", "The story"),
            ("shot-notes.png", "ADK Lens screenshot: notes on the board.", "Your notes, ready to copy as a prompt.", "The notes"),
            ("shot-checks.png", "ADK Lens screenshot: on the harder demo, a safety check stopped a request and the board shows it as a step.", "A safety check stops a request, and you see it.", "The checks"),
        ],
        "setup_title": "Set it up with your coding agent",
        "setup_text": "Copy the prompt and paste it into your coding agent, in your project folder. It finds your ADK project and puts ADK Lens on top. No ADK project yet? It offers to create your first agent.",
        "prompt_label": "Setup prompt",
        "steps": ["Copy the prompt", "Paste it into your agent", "It finds your agents, or creates one"],
        "open_title": "Open source. Free.",
        "open_text": "MIT licence. The code is public: read it, reuse it, improve it. If ADK Lens helps you, a coffee keeps me building.",
        "open_btn": "See the code on GitHub", "coffee_btn": "Buy me a coffee",
        "faq_title": "Questions",
        "foot_title": "A live whiteboard for your ADK agents.",
        "links_label": "Useful links", "source": "Source code", "issues": "Report a problem", "x": "@AlexCormeraie on X", "legal": "Legal notice",
        "made": "Made in Paris.", "indie": "Independent project, not affiliated with Google.",
        "other": "Version française",
    },
    "fr": {
        "skip": "Aller au contenu", "home": "accueil", "nav_label": "Sections", "lang_label": "English version", "lang_short": "EN",
        "nav": [("#try", "Essayer"), ("#features", "Ce que ça fait"), ("#agent", "Installer"), ("#faq", "Questions")],
        "try_title": "Essaie-le ici", "try_text": "Choisis une demande et regarde-la traverser les agents. Rien à installer.",
        "copy": "Copier le prompt d'installation", "copy_short": "Copier le prompt", "copied": "Prompt copié", "copied_live": "Prompt copié. Colle-le dans ton agent de code.",
        "works": "Fonctionne avec Claude Code, Codex, Antigravity et Gemini CLI, Cursor, GitHub Copilot, Windsurf, ou n'importe quel agent de code.",
        "any": "n'importe quel agent",
        "prompt": "Prépare mon week-end", "you": "TON PROMPT", "agent": "AGENTS", "tool": "OUTIL",
        "sticky": ["Pourquoi la météo", "d'abord ?"],
        "board_label": "Illustration : un prompt passe d'un agent à l'autre sur un tableau blanc pointillé, à côté d'un post-it.",
        "caption": "Démo du site, avec les agents de l'exemple fourni. Le vrai tableau dessine les tiens.",
        "statement": "ADK Lens se branche sur ADK et dessine en direct ce que font tes agents. Rien à changer dans ton code.",
        "story": ["Tu demandes un programme de week-end.", "concierge passe la main à weather_agent.", "weather_agent appelle get_weather.", "planner rédige la réponse."],
        "note": "Pourquoi la météo d'abord ?", "as_prompt": "Copier comme prompt",
        "check": ["Le contrôle de sécurité ", "screen_prompt", " a arrêté la demande."], "harder": "Envie d'un cas plus corsé ? Lance ensuite",
        "shots_title": "En vrai", "shots_tabs": "Captures d'écran",
        "copy_fail": "Ton navigateur a bloqué la copie.", "copy_fail_link": "Ouvrir le guide d'installation",
        "manual": "Pas d'agent de code ? Fais-le à la main", "manual_copy": "Copier les deux commandes", "manual_copied": "Commandes copiées", "manual_live": "Commandes copiées. Colle-les dans ton terminal.",
        "shots": [
            ("shot-map.png", "Capture d'ADK Lens : la carte des agents et des outils, en blocs droits et flèches à angle droit.", "La carte de tes agents et de tes outils, dessinée comme un schéma d'architecture.", "La carte"),
            ("shot-linear.png", "Capture d'ADK Lens : la vue Récit d'une exécution.", "Une exécution, racontée en mots simples.", "Le récit"),
            ("shot-notes.png", "Capture d'ADK Lens : des notes sur le tableau.", "Tes notes, prêtes à copier comme prompt.", "Les notes"),
            ("shot-checks.png", "Capture d'ADK Lens : dans la démo corsée, un contrôle de sécurité a arrêté une demande et le tableau l'affiche comme une étape.", "Un contrôle de sécurité arrête une demande, et tu le vois.", "Les contrôles"),
        ],
        "setup_title": "Installe-le avec ton agent de code",
        "setup_text": "Copie le prompt et colle-le dans ton agent de code, dans le dossier de ton projet. Il trouve ton projet ADK et pose ADK Lens par-dessus. Pas encore de projet ADK ? Il te propose de créer ton premier agent.",
        "prompt_label": "Prompt d'installation",
        "steps": ["Copie le prompt", "Colle-le dans ton agent", "Il trouve tes agents, ou en crée un"],
        "open_title": "Open source. Gratuit.",
        "open_text": "Licence MIT. Le code est public : lis-le, réutilise-le, améliore-le. Si ADK Lens te rend service, un café m'aide à continuer.",
        "open_btn": "Voir le code sur GitHub", "coffee_btn": "Offrir un café",
        "faq_title": "Questions",
        "foot_title": "Le tableau blanc en direct de tes agents ADK.",
        "links_label": "Liens utiles", "source": "Code source", "issues": "Signaler un souci", "x": "@AlexCormeraie sur X", "legal": "Mentions légales",
        "made": "Fait à Paris.", "indie": "Projet indépendant, non affilié à Google.",
        "other": "English version",
    },
}


def icon(file: str, size: int = 20) -> str:
    svg = (ICONS / file).read_text(encoding="utf-8")
    svg = svg.split("</title>", 1)[-1] if "<title>" in svg else svg.split(">", 1)[1]
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="currentColor" aria-hidden="true" focusable="false">'
            + svg.replace("</svg>", "").strip() + "</svg>")


def agents(lang: str) -> list[tuple[str, str]]:
    mono = lambda ch: f'<span class="mono-chip" aria-hidden="true">{ch}</span>'
    return [
        (icon("claude.svg"), "Claude Code"),
        (icon("openai.svg"), "Codex"),
        (icon("googlegemini.svg"), "Antigravity · Gemini CLI"),
        (mono("C"), "Cursor"),
        (icon("githubcopilot.svg"), "GitHub Copilot"),
        (icon("windsurf.svg"), "Windsurf"),
        (mono("+"), T[lang]["any"]),
    ]


def rotator(lang: str) -> str:
    items = agents(lang)
    spans = "".join(f'<span class="rot__item">{i}{e(label)}</span>' for i, label in items)
    spans += f'<span class="rot__item rot__item--dup">{items[0][0]}{e(items[0][1])}</span>'
    return (f'<div class="rot"><div class="rot__list" aria-hidden="true">{spans}</div>'
            f'<span class="sr-only">{e(T[lang]["works"])}</span></div>')


def copy_button(lang: str, prompt: str, label: str, cls: str = "btn btn--primary") -> str:
    t = T[lang]
    return (f'<button class="{cls}" type="button" data-copy="{e(prompt)}" data-copied="{e(t["copied_live"])}" '
            f'data-fail="{e(t["copy_fail"])}" data-fail-link="{e(t["copy_fail_link"])}" data-fail-href="{REPO}/blob/main/AGENT-SETUP.md">'
            f'<span class="is-idle">{e(label)}</span><span class="is-done" aria-hidden="true">{e(t["copied"])}</span></button>')


SHIELD = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 3v5c0 4.6-2.9 8.3-7 10-4.1-1.7-7-5.4-7-10V6l7-3Z"/><path d="m9 12 2 2 4-4"/></svg>'
MANUAL = ['pip install "git+https://github.com/Connected-Mate/adk-lens"', "adk-lens demo"]


def manual(lang: str) -> str:
    """The by-hand path, folded away: two terminal commands (never the prompt text)."""
    t = T[lang]
    lines = "".join(f"<code>{e(c)}</code>" for c in MANUAL)
    return (f'<details class="manual"><summary>{e(t["manual"])}</summary><div class="manual__in"><div class="manual__cmd">{lines}</div>'
            f'<p class="manual__more">{e(t["harder"])} <code>adk-lens demo hard</code></p>'
            f'<button class="btn btn--soft btn--sm" type="button" data-copy="{e(chr(10).join(MANUAL))}" data-copied="{e(t["manual_live"])}">'
            f'<span class="is-idle">{e(t["manual_copy"])}</span><span class="is-done" aria-hidden="true">{e(t["manual_copied"])}</span></button></div></details>')


def board_svg(lang: str) -> str:
    t = T[lang]
    return f"""<svg viewBox="0 0 720 440" role="img" aria-label="{e(t['board_label'])}">
  <path class="b-line" d="M230 224 H290"/>
  <path class="b-line" d="M440 224 H462 Q470 224 470 216 V124 Q470 116 478 116 H500"/>
  <path class="b-line" d="M440 224 H462 Q470 224 470 232 V328 Q470 336 478 336 H500"/>
  <path class="b-line" d="M595 142 V190" stroke-dasharray="2 5"/>
  <circle class="b-dot b-dot--a" r="6"/>
  <circle class="b-dot b-dot--b" r="6"/>
  <text class="b-tag" x="24" y="186">{e(t['you'])}</text>
  <g class="b-node b-node--you"><rect x="20" y="198" width="210" height="52" rx="8"/><text x="125" y="230" text-anchor="middle">{e(t['prompt'])}</text></g>
  <text class="b-tag" x="294" y="186">{e(t['agent'])}</text>
  <g class="b-node"><rect x="290" y="198" width="150" height="52" rx="8"/><text x="365" y="230" text-anchor="middle">concierge</text></g>
  <g class="b-node"><rect x="500" y="90" width="190" height="52" rx="8"/><text x="595" y="122" text-anchor="middle">weather_agent</text></g>
  <g class="b-node b-node--tool"><rect x="520" y="190" width="150" height="44" rx="6"/><text x="595" y="217" text-anchor="middle">get_weather</text></g>
  <g class="b-node"><rect x="500" y="310" width="140" height="52" rx="8"/><text x="570" y="342" text-anchor="middle">planner</text></g>
  <g class="b-note" transform="rotate(-3 135 350)"><rect x="50" y="306" width="170" height="92" rx="3"/><text x="68" y="344">{e(t['sticky'][0])}</text><text x="68" y="366">{e(t['sticky'][1])}</text></g>
</svg>"""


def rows(lang: str) -> str:
    t = T[lang]
    f = SHEET["features"]
    story = "".join(f"<li>{e(x)}</li>" for x in t["story"])
    visuals = [
        f'<div class="card card--a zoom" aria-hidden="true"><div class="card__in"><div class="sheet"><div class="track"><b></b><b></b><b></b><b></b><u></u></div></div>'
        f'<div class="sheet"><ul class="story">{story}</ul></div></div></div>',
        f'<div class="card card--b zoom" aria-hidden="true"><div class="card__in"><div class="note">{e(t["note"])}</div>'
        f'<div class="pair"><span class="chip chip--amber"><i></i>planner</span><span class="chip chip--btn">{e(t["as_prompt"])}</span></div></div></div>',
        '<div class="card card--c zoom" aria-hidden="true"><div class="versions">'
        '<div class="sheet"><span class="caption">v1</span><span class="chip"><i></i>concierge</span><span class="chip chip--amber"><i></i>planner</span></div>'
        '<div class="sheet"><span class="caption">v2</span><span class="chip"><i></i>concierge</span><span class="chip chip--amber"><i></i>planner</span><span class="chip chip--green chip--new"><i></i>weather_agent</span></div>'
        '</div></div>',
        f'<div class="card card--d zoom" aria-hidden="true"><div class="card__in"><span class="chip chip--shield">{SHIELD}station_desk</span>'
        f'<div class="sheet"><p class="check">{SHIELD}<span>{e(t["check"][0])}<b>{e(t["check"][1])}</b>{e(t["check"][2])}</span></p></div></div></div>',
    ]
    out = []
    for feat, visual in zip(f[1:5], visuals):
        out.append(f"""  <article class="row">
    <div class="row__text"><h2 class="h2">{e(feat['title'][lang])}</h2><p class="body">{e(feat['text'][lang])}</p></div>
    {visual}
  </article>""")
    return "\n".join(out)


def body(lang: str, prefix: str, other_href: str) -> str:
    t = T[lang]
    other = "fr" if lang == "en" else "en"
    key = f'{SHEET["slug"]}-lang'
    prompt = SHEET["agent_setup"]["prompt"][lang]
    name = SHEET["name"]
    nav = "".join(f'<a href="{h}">{e(label)}</a>' for h, label in t["nav"])
    chips = "".join(f"<li>{i}{e(label)}</li>" for i, label in agents(lang))
    steps = "".join(f"<li>{e(s)}</li>" for s in t["steps"])
    shots = "\n".join(
        f'    <figure class="shot" data-shot="{prefix}assets/{f}" data-alt="{e(alt)}" data-tab="{e(tab)}" hidden><figcaption class="small body">{e(cap)}</figcaption></figure>'
        for f, alt, cap, tab in t["shots"])
    nb = lambda x: e(x).replace(" ?", "&nbsp;?").replace(" :", "&nbsp;:").replace("« ", "«&nbsp;").replace(" »", "&nbsp;»")  # French spacing
    faq = "\n".join(f'      <details class="qa"><summary>{nb(q["q"][lang])}</summary><p>{nb(q["a"][lang])}</p></details>' for q in SHEET["faq"])
    lang_link = (f'<a class="lang" href="{other_href}" data-lang="{other}" data-lang-key="{key}" hreflang="{other}" lang="{other}" '
                 f'aria-label="{e(t["lang_label"])}">{t["lang_short"]}</a>')
    return f"""<body>
<a class="skip" href="#content">{e(t['skip'])}</a>
<header class="top">
  <div class="wrap top__in">
    <a class="mark" href="./" aria-label="{e(name)}, {e(t['home'])}"><img src="{prefix}assets/icon-192.png" alt="" width="24" height="24"><span>{e(name)}</span></a>
    <nav class="nav" aria-label="{e(t['nav_label'])}">{nav}</nav>
    <div class="top__end"><a class="btn btn--primary btn--sm" href="{REPO}" rel="noopener">GitHub</a>{lang_link}</div>
  </div>
</header>
<main id="content">
<section class="wrap hero" aria-labelledby="title">
  <canvas class="field field--css" aria-hidden="true"></canvas>
  <div class="hero__in">
    <p class="lockup"><img src="{prefix}assets/icon-192.png" alt="" width="32" height="32"><span>{e(name)}</span></p>
    <h1 class="h1" id="title">{e(SHEET['headline'][lang])}</h1>
    <p class="body">{e(SHEET['lede'][lang])}</p>
    <div class="cta">{copy_button(lang, prompt, t['copy'])}{rotator(lang)}</div>
    <p class="fine">{e(SHEET['platform'][lang])}</p>
  </div>
</section>
<section class="wrap stage" id="try" aria-labelledby="try-title">
  <div class="stage__head"><h2 class="h2" id="try-title">{e(t['try_title'])}</h2><p class="body">{e(t['try_text'])}</p></div>
  <div class="board zoom"><div class="board__canvas play" data-play data-lang="{lang}">{board_svg(lang)}</div></div>
  <p class="caption">{e(t['caption'])}</p>
</section>
<section class="wrap statement" id="features" aria-label="{e(t['nav'][1][1])}">
  <p><span>{e(t['statement'])}</span></p>
</section>
<section class="wrap rows" aria-label="{e(t['nav'][1][1])}">
{rows(lang)}
</section>
<section class="wrap shots" id="shots" data-shots hidden aria-labelledby="shots-title">
  <div class="shots__head"><h2 class="h2" id="shots-title">{e(t['shots_title'])}</h2><div class="shots__tabs" role="group" aria-label="{e(t['shots_tabs'])}" data-shot-tabs></div></div>
  <div class="shots__frame zoom">
{shots}
  </div>
</section>
<section class="wrap setup" id="agent" aria-labelledby="agent-title">
  <div class="setup__panel">
    <h2 class="h2" id="agent-title">{e(t['setup_title'])}</h2>
    <p class="body">{e(t['setup_text'])}</p>
    <ul class="agents" role="list">{chips}</ul>
    {copy_button(lang, prompt, t['copy_short'])}
    <ol class="steps small">{steps}</ol>
    {manual(lang)}
  </div>
</section>
<section class="night" id="source" aria-labelledby="source-title">
  <h2 class="h2" id="source-title">{e(t['open_title'])}</h2>
  <p class="body">{e(t['open_text'])}</p>
  <div class="cta"><a class="btn btn--white" href="{REPO}" rel="noopener">{e(t['open_btn'])}</a><a class="btn btn--glass" href="{SHEET['coffee']['url']}" rel="noopener" data-coffee>{e(t['coffee_btn'])}</a></div>
</section>
<section class="wrap faq" id="faq" aria-labelledby="faq-title">
  <h2 class="h2" id="faq-title">{e(t['faq_title'])}</h2>
  <div>
{faq}
  </div>
</section>
</main>
<footer class="wrap foot">
  <div class="foot__top">
    <p class="foot__title">{e(t['foot_title'])}</p>
    <nav class="foot__links" aria-label="{e(t['links_label'])}"><a href="{REPO}" rel="noopener">{e(t['source'])}</a><a href="{REPO}/issues" rel="noopener">{e(t['issues'])}</a><a href="{SHEET['coffee']['url']}" rel="noopener">{e(t['coffee_btn'])}</a><a href="{SHEET['links']['x']}" rel="noopener">{e(t['x'])}</a></nav>
  </div>
  <p class="wordmark" aria-hidden="true">{e(name)}</p>
  <div class="foot__end"><span>© {date.today().year} Connected Mate. {e(t['made'])}</span><span>{e(t['indie'])}</span><a href="{LEGAL[lang]}">{e(t['legal'])}</a><a href="{other_href}" data-lang="{other}" data-lang-key="{key}" hreflang="{other}" lang="{other}">{e(t['other'])}</a></div>
</footer>
<script src="{prefix}lens.js" defer></script>
<script src="{prefix}play.js" defer></script>
</body>
</html>
"""


def must(pattern: str, repl, text: str) -> str:
    out, n = re.subn(pattern, repl, text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"customize_site: pattern not found: {pattern[:60]}")
    return out


def customize(path: Path, lang: str, prefix: str, other_href: str) -> None:
    s = path.read_text(encoding="utf-8")
    if "lens.css" in s:
        raise SystemExit(f"{path} already customised: re-run scaffold.py --force first")
    head = s.split("<body>", 1)[0]
    head = must(r'<link rel="stylesheet" href="[^"]*style\.css[^"]*">\n?',
                lambda m: (f'<link rel="preload" href="{prefix}assets/fonts/google-sans-flex-latin.woff2" as="font" type="font/woff2" crossorigin>\n'
                           f'<link rel="stylesheet" href="{prefix}lens.css">\n'), head)
    head = must(r'<style>@media \(prefers-color-scheme.*?</style>\n?', lambda m: "", head)
    path.write_text(head + body(lang, prefix, other_href), encoding="utf-8")
    print(f"customised {path.relative_to(ROOT)}")


def main() -> int:
    default = SHEET["default_lang"]
    other = "fr" if default == "en" else "en"
    customize(DOCS / "index.html", default, "", f"{other}/")
    customize(DOCS / other / "index.html", other, "../", "../")
    # 404 page: same stylesheet, same classes
    p = DOCS / "404.html"
    s = p.read_text(encoding="utf-8")
    s = (s.replace("style.css", "lens.css").replace('class="display"', 'class="h1"').replace('class="lede"', 'class="body"')
          .replace("btn btn--go", "btn btn--primary"))
    p.write_text(s, encoding="utf-8")
    for leftover in ("style.css", "site.js"):
        (DOCS / leftover).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
