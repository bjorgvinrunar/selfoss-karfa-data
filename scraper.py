#!/usr/bin/env python3
"""
Selfoss Körfubolti — KKÍ/MBT gagnasækir v4
Les kki.js til að finna API endapunktana, sækir svo gögn beint.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

TEAMS = [
    {"key": "karlar",   "name": "Meistaraflokkur karla",   "league_id": 191, "season_id": 130402, "team_id": 4695391, "color": "#1a3a6b"},
    {"key": "konur",    "name": "Meistaraflokkur kvenna",   "league_id": 231, "season_id": 130421, "team_id": 4765539, "color": "#6b1a3a"},
    {"key": "u_karlar", "name": "Selfoss U",                "league_id": 232, "season_id": 130496, "team_id": 4772377, "color": "#1a5a3a"},
    {"key": "fl12",     "name": "12. flokkur drengja",      "league_id": 192, "season_id": 130492, "team_id": 4749665, "color": "#3a1a6b"},
    {"key": "fl11",     "name": "11. flokkur drengja",      "league_id": 195, "season_id": 130490, "team_id": 4749663, "color": "#5a3a1a"},
    {"key": "fl10d",    "name": "10. flokkur drengja",      "league_id": 196, "season_id": 130486, "team_id": 4735179, "color": "#1a5a5a"},
    {"key": "fl9",      "name": "9. flokkur drengja",       "league_id": 197, "season_id": 130497, "team_id": 4725337, "color": "#5a1a1a"},
    {"key": "fl10s",    "name": "10. flokkur stúlkna",      "league_id": 193, "season_id": 130488, "team_id": 4772386, "color": "#6b1a5a"},
]

KKI_JS_URL = "https://web1.mbt.lt/prod/snakesilver-client/integration/kki.js?v=11"

def kki_url(team):
    return (
        f"https://kki.is/motamal/leikir-og-urslit/motayfirlit/Eitt-lid"
        f"?league_id={team['league_id']}"
        f"&season_id={team['season_id']}"
        f"&team_id={team['team_id']}"
    )

def normalize_game(g):
    if not isinstance(g, dict):
        return None
    date_str = (
        g.get("start_date") or g.get("date") or g.get("game_date") or
        g.get("start_time") or g.get("time") or g.get("gameDate") or
        g.get("startDate") or g.get("scheduled") or ""
    )
    home_team = g.get("home_team") or {}
    away_team = g.get("away_team") or {}
    home = (
        g.get("home_team_name") or
        (home_team.get("name") if isinstance(home_team, dict) else str(home_team)) or
        g.get("homeTeamName") or g.get("homeTeam") or g.get("home") or ""
    )
    away = (
        g.get("away_team_name") or
        (away_team.get("name") if isinstance(away_team, dict) else str(away_team)) or
        g.get("awayTeamName") or g.get("awayTeam") or g.get("away") or ""
    )
    sh = g.get("home_score") if g.get("home_score") is not None else g.get("homeScore")
    sa = g.get("away_score") if g.get("away_score") is not None else g.get("awayScore")
    venue = g.get("arena") or g.get("arena_name") or g.get("venue") or g.get("location") or ""
    if not date_str and not home and not away:
        return None
    return {
        "date": str(date_str),
        "home": str(home),
        "away": str(away),
        "home_score": sh,
        "away_score": sa,
        "venue": str(venue),
    }

def extract_games(data):
    if isinstance(data, list) and len(data) > 0:
        return data
    if isinstance(data, dict):
        for key in ["games", "data", "matches", "results", "items", "schedule", "list"]:
            if key in data and isinstance(data[key], list) and len(data[key]) > 0:
                return data[key]
    return []

def fetch_url(page, url, label=""):
    """Sækir URL í gegnum Playwright með kki.is context."""
    try:
        result = page.evaluate("""
            async (url) => {
                try {
                    const resp = await fetch(url, {
                        method: 'GET',
                        headers: {
                            'Accept': 'application/json, text/javascript, */*',
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                        credentials: 'omit',
                    });
                    const text = await resp.text();
                    return { ok: resp.ok, status: resp.status, body: text };
                } catch(e) {
                    return { ok: false, error: e.message };
                }
            }
        """, url)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}

def parse_kki_js(js_content):
    """
    Les kki.js og finnur API base URL og endapunktana.
    Leitar að strengjum eins og 'api/v1', '/games', '/teams' osfrv.
    """
    print(f"\nGreini kki.js ({len(js_content)} stafir)...")

    # Vista kki.js til greiningar
    os.makedirs("data", exist_ok=True)
    with open("data/kki_js_debug.txt", "w") as f:
        f.write(js_content[:50000])  # Fyrstu 50k stafir

    # Leitar að URL mynstrum í JS kóðanum
    findings = {}

    # Base URL
    base_urls = re.findall(r'["\']https?://[^"\']*mbt\.lt[^"\']*["\']', js_content)
    findings["mbt_base_urls"] = list(set(base_urls))

    # API slóðir
    api_paths = re.findall(r'["\'](/[a-z0-9_/{}]+(?:games|matches|schedule|results)[^"\']*)["\']', js_content)
    findings["api_paths"] = list(set(api_paths))

    # Allar slóðir með 'game' eða 'match'
    game_strings = re.findall(r'["\']([^"\']*(?:game|match|schedule)[^"\']{0,50})["\']', js_content, re.IGNORECASE)
    findings["game_strings"] = list(set(game_strings))[:20]

    # Leitar að season_id, team_id, league_id í samhengi
    id_patterns = re.findall(r'["\']([^"\']*(?:season|team|league)[^"\']{0,100})["\']', js_content, re.IGNORECASE)
    findings["id_patterns"] = list(set(id_patterns))[:20]

    print(f"  MBT base URLs: {findings['mbt_base_urls']}")
    print(f"  API slóðir: {findings['api_paths']}")
    print(f"  Game strengir: {findings['game_strings'][:5]}")

    return findings

def build_api_urls_from_js(js_findings, team):
    """Byggir upp mögulegar API slóðir út frá kki.js greiningu."""
    lid = team["league_id"]
    sid = team["season_id"]
    tid = team["team_id"]

    urls = []

    # Ef við fundum base URLs í JS
    for base in js_findings.get("mbt_base_urls", []):
        base = base.strip("'\"")
        for path in js_findings.get("api_paths", []):
            path = path.strip("'\"")
            # Prófum að setja inn breyturnar
            for p in [
                path.replace("{league_id}", str(lid)).replace("{season_id}", str(sid)).replace("{team_id}", str(tid)),
                path.replace("{leagueId}", str(lid)).replace("{seasonId}", str(sid)).replace("{teamId}", str(tid)),
            ]:
                if str(lid) in p or str(sid) in p or str(tid) in p:
                    urls.append(base.rstrip("/") + "/" + p.lstrip("/"))

    # Alltaf bætum við þessum staðlaðu prófum
    standard = [
        f"https://web1.mbt.lt/prod/api/v1/leagues/{lid}/seasons/{sid}/teams/{tid}/games",
        f"https://web1.mbt.lt/prod/api/v1/seasons/{sid}/teams/{tid}/games",
        f"https://web1.mbt.lt/prod/api/v1/teams/{tid}/games?season_id={sid}",
        f"https://web1.mbt.lt/prod/api/v1/teams/{tid}/schedule?season_id={sid}",
        f"https://web1.mbt.lt/prod/api/v2/leagues/{lid}/seasons/{sid}/teams/{tid}/games",
        f"https://web1.mbt.lt/prod/api/leagues/{lid}/seasons/{sid}/teams/{tid}/games.json",
        f"https://web1.mbt.lt/prod/snakesilver/api/leagues/{lid}/seasons/{sid}/teams/{tid}/games",
        f"https://web1.mbt.lt/prod/snakesilver/api/teams/{tid}/games?season={sid}",
    ]
    urls.extend(standard)
    return urls

def main():
    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "teams": [],
        "debug": {}
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            extra_http_headers={
                "Accept-Language": "is-IS,is;q=0.9,en;q=0.8",
                "Referer": "https://kki.is/",
            }
        )
        page = context.new_page()

        # Förum á kki.is til að setja upp session
        print("1. Hleð kki.is...")
        try:
            page.goto("https://kki.is", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(1000)
            print("   ✓")
        except Exception as e:
            print(f"   ⚠ {e}")

        # Sækjum og greinum kki.js
        print(f"\n2. Sæki kki.js: {KKI_JS_URL}")
        js_result = fetch_url(page, KKI_JS_URL, "kki.js")
        js_findings = {}

        if js_result.get("ok") and js_result.get("body"):
            js_content = js_result["body"]
            print(f"   ✓ Sótt ({len(js_content)} stafir)")
            js_findings = parse_kki_js(js_content)
            output["debug"]["kki_js_findings"] = js_findings
        else:
            print(f"   ✗ Tókst ekki: {js_result.get('error', js_result.get('status'))}")

        # Sækjum gögn fyrir hvert lið
        print("\n3. Sæki leikjagögn...")
        for i, team in enumerate(TEAMS):
            print(f"\n[{i+1}/{len(TEAMS)}] {team['name']}")
            games = []

            api_urls = build_api_urls_from_js(js_findings, team)

            for url in api_urls:
                print(f"  → {url}")
                result = fetch_url(page, url)

                if not result.get("ok"):
                    print(f"     ✗ HTTP {result.get('status', '?')} / {result.get('error', '')}")
                    continue

                body = result.get("body", "")
                if not body:
                    print(f"     ✗ Tómt svar")
                    continue

                # Prófum JSON parse
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    # Kannski texti sem gefur okkur vísbendingu
                    print(f"     ✗ Ekki JSON — svar: {body[:100]}")
                    continue

                found = extract_games(data)
                if found:
                    print(f"     ✓ FANN {len(found)} LEIKI!")
                    normalized = [normalize_game(g) for g in found]
                    games = [g for g in normalized if g is not None]
                    break
                else:
                    print(f"     ~ JSON en engin leikjalisti. Lyklar: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")

            output["teams"].append({
                "key":       team["key"],
                "name":      team["name"],
                "color":     team["color"],
                "league_id": team["league_id"],
                "season_id": team["season_id"],
                "team_id":   team["team_id"],
                "kki_url":   kki_url(team),
                "games":     games,
            })

        browser.close()

    # Vista JSON
    os.makedirs("data", exist_ok=True)
    with open("data/games.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Yfirlit
    print(f"\n{'='*60}")
    total = sum(len(t["games"]) for t in output["teams"])
    for t in output["teams"]:
        n = len(t["games"])
        print(f"  {'✓' if n else '✗'} {t['name']}: {n} leikir")
    print(f"  Samtals: {total} leikir")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
