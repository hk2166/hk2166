#!/usr/bin/env python3
"""Render a `top`-style SVG of recent commit activity across a user's public repos.

Every public, non-fork repo pushed in the last 30 days is a "process". Its %CPU is its
share of all commits made across those repos in that window. Stdlib only, so the
workflow needs no install step.

    GITHUB_TOKEN=... python3 .github/scripts/top.py dist/top.svg
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

USER = os.environ.get("PROFILE_USER", "hk2166")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
OUT = sys.argv[1] if len(sys.argv) > 1 else "dist/top.svg"
IST = timezone(timedelta(hours=5, minutes=30))
WINDOW = timedelta(days=30)
MAX_ROWS = 8
# Public repos to leave off the board, comma-separated (e.g. work repos).
EXCLUDE = {r.strip() for r in os.environ.get("PROFILE_EXCLUDE", "").split(",") if r.strip()}

# Palette and metrics shared with assets/header.svg.
BG, BAR, BORDER = "#0e1014", "#171a21", "#2a2f3a"
FG, DIM, AMBER, GREEN, CYAN = "#d5dae3", "#7a8291", "#ffb454", "#8ddb8c", "#79c0ff"
W, PAD, LINE, TITLE_H = 880, 24, 22, 34


def get(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": f"{USER}-profile-top"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def commit_dates(repo, since):
    dates = []
    for page in range(1, 11):
        try:
            batch = get(f"/repos/{USER}/{repo}/commits?since={since}&per_page=100&page={page}")
        except urllib.error.HTTPError as e:
            if e.code == 409:  # empty repository
                return dates
            raise
        dates += [parse(c["commit"]["committer"]["date"]) for c in batch]
        if len(batch) < 100:
            break
    return dates


def ago(dt, now):
    s = (now - dt).total_seconds()
    if s < 3600:
        return f"{max(1, int(s // 60))}m ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    return f"{int(s // 86400)}d ago"


def truncate(name, width):
    # top marks a cut-off COMMAND with a trailing "+".
    return name if len(name) <= width else name[:width - 1] + "+"


def uptime(created, now):
    months = (now.year - created.year) * 12 + now.month - created.month - (now.day < created.day)
    return f"{months // 12}y {months % 12}m"


def collect():
    now = datetime.now(timezone.utc)
    since = (now - WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ")
    user = get(f"/users/{USER}")
    repos = [r for r in get(f"/users/{USER}/repos?per_page=100&type=owner&sort=pushed")
             if not r["fork"] and not r["archived"] and r["name"] not in EXCLUDE]
    procs = []
    for r in repos:
        if parse(r["pushed_at"]) < now - WINDOW:
            continue
        dates = commit_dates(r["name"], since)
        if dates:
            procs.append({"repo": r, "dates": dates, "last": max(dates)})
    procs.sort(key=lambda p: (len(p["dates"]), p["last"]), reverse=True)
    return now, user, repos, procs


def render(now, user, repos, procs):
    all_dates = [d for p in procs for d in p["dates"]]
    total = len(all_dates)
    load = [sum(d > now - timedelta(days=n) for d in all_dates) / n for n in (1, 7, 30)]

    langs = {}
    for p in procs:
        lang = p["repo"]["language"] or "Other"
        langs[lang] = langs.get(lang, 0) + len(p["dates"])
    ranked = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)
    shown = ranked[:3]
    rest = sum(n for _, n in ranked[3:])
    if rest:
        shown.append(("other", rest))

    local = now.astimezone(IST)
    out = []
    y = TITLE_H + PAD + 4

    def line(parts, cls="", delay=None):
        # parts: list of (text, css class) runs laid out as tspans on one line.
        nonlocal y
        spans = "".join(f'<tspan class="{c}">{escape(t)}</tspan>' if c else escape(t) for t, c in parts)
        style = f' style="animation-delay:{delay:.2f}s"' if delay is not None else ""
        out.append(f'<text x="{PAD}" y="{y}" class="{cls}"{style}>{spans}</text>')
        y += LINE

    n = lambda v: (v, "n")
    line([("top - ", ""), n(local.strftime("%H:%M:%S")), (" up ", ""), n(uptime(parse(user["created_at"]), now)),
          (",  1 user,  load average: ", ""), n(f"{load[0]:.2f}"), (", ", ""), n(f"{load[1]:.2f}"),
          (", ", ""), n(f"{load[2]:.2f}")])
    line([("Tasks: ", ""), n(str(len(repos))), (" total,  ", ""), n(str(len(procs))), (" running,  ", ""),
          n(str(len(repos) - len(procs))), (" sleeping     Commits: ", ""), n(str(total)), (" in 30d", "")])
    lang_runs = [("%Lang: ", "")]
    for i, (name, count) in enumerate(shown):
        lang_runs += [n(f"{100 * count / total:.1f}" if total else "0.0"), (f" {name}" + (", " if i < len(shown) - 1 else ""), "")]
    line(lang_runs)
    y += LINE // 2

    cols = [("PID", 0, "end", 40), ("USER", 56, "start", 0), ("S", 132, "start", 0), ("%CPU", 196, "end", 0),
            ("COMMITS", 400, "end", 0), ("LAST", 422, "start", 0), ("LANG", 512, "start", 0),
            ("COMMAND", 628, "start", 0)]
    bar_x, bar_w = 210, 120

    out.append(f'<rect x="{PAD - 6}" y="{y - 15}" width="{W - 2 * PAD + 12}" height="{LINE - 2}" fill="{FG}"/>')
    for name, x, anchor, off in cols:
        out.append(f'<text x="{PAD + x + off}" y="{y}" text-anchor="{anchor}" class="hd">{name}</text>')
    y += LINE

    if not procs:
        line([("  no commits in the last 30 days. the machine is idle.", "d")])
    top_share = len(procs[0]["dates"]) / total if procs else 1
    for i, p in enumerate(procs[:MAX_ROWS]):
        r, commits = p["repo"], len(p["dates"])
        share = commits / total
        running = p["last"] > now - timedelta(hours=24)
        delay = 0.25 + 0.07 * i
        cells = [str(r["id"] % 100000), USER, "R" if running else "S", f"{100 * share:.1f}", str(commits),
                 ago(p["last"], now), r["language"] or "-", truncate(r["name"], 26)]
        row = [f'<g class="row" style="animation-delay:{delay:.2f}s">']
        for (name, x, anchor, off), cell in zip(cols, cells):
            cls = {"S": "g b" if running else "d", "COMMAND": "c b" if running else "c",
                   "%CPU": "n", "COMMITS": "n", "PID": "d", "LAST": "d"}.get(name, "")
            row.append(f'<text x="{PAD + x + off}" y="{y}" text-anchor="{anchor}" class="{cls}">{escape(cell)}</text>')
        width = max(2, bar_w * share / top_share)
        row.append(f'<rect x="{PAD + bar_x}" y="{y - 10}" width="{bar_w}" height="8" rx="1" fill="{BORDER}"/>')
        row.append(f'<rect class="bar" style="animation-delay:{delay + 0.1:.2f}s" x="{PAD + bar_x}" y="{y - 10}" '
                   f'width="{width:.1f}" height="8" rx="1" fill="{AMBER}"/>')
        row.append("</g>")
        out.append("".join(row))
        y += LINE

    y += LINE // 2
    line([(f"refreshed {local:%Y-%m-%d %H:%M} IST from public repos only, every 6h by .github/workflows/profile.yml", "d")])
    h = y + PAD // 2 - 6

    body = "\n  ".join(out)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" width="{W}" height="{h}" viewBox="0 0 {W} {h}" role="img" aria-label="top: {total} commits across {len(procs)} active public repos in the last 30 days">
  <style>
    text {{ font: 13.5px ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace; fill: {FG}; white-space: pre; }}
    .n {{ fill: {AMBER}; }} .d {{ fill: {DIM}; }} .g {{ fill: {GREEN}; }} .c {{ fill: {CYAN}; }} .b {{ font-weight: 700; }}
    .hd {{ fill: {BG}; font-weight: 700; }} .t {{ fill: {DIM}; font-size: 12px; }}
    .row {{ animation: in .3s ease-out both; }}
    .bar {{ transform-box: fill-box; transform-origin: left; animation: grow .7s cubic-bezier(.2,.7,.2,1) both; }}
    @keyframes in {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
    @keyframes grow {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
    @media (prefers-reduced-motion: reduce) {{ .row, .bar {{ animation: none; }} }}
  </style>
  <rect x=".5" y=".5" width="{W - 1}" height="{h - 1}" rx="10" fill="{BG}" stroke="{BORDER}"/>
  <path d="M.5 {TITLE_H}V10.5a10 10 0 0 1 10-10h{W - 21}a10 10 0 0 1 10 10V{TITLE_H}z" fill="{BAR}"/>
  <line x1=".5" y1="{TITLE_H}" x2="{W - .5}" y2="{TITLE_H}" stroke="{BORDER}"/>
  <text x="{W / 2}" y="{TITLE_H / 2 + 4}" text-anchor="middle" class="t">hemant --top</text>
  {body}
</svg>
'''


if __name__ == "__main__":
    svg = render(*collect())
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w") as f:
        f.write(svg)
    print(f"wrote {OUT}")
