#!/usr/bin/env python3
"""
Selfoss Körfubolti — KKÍ/MBT gagnasækir v3
Kallar beint á MBT API með kki.is Origin/Referer til að komast framhjá CORS.
"""

import json
import os
import time
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

# MBT API endapunktar sem við reynum fyrir hvert lið
# {0}=league_id, {1}=season_id, {2}=team_id
MBT_URLS = [
    "https://web1.mbt.lt/prod/api/v1/leagues/{0}/seasons/{1}/teams/{2}/games",
    "https://web1.mbt.lt/prod/api/v1/seasons/{1}/teams/{2}/games",
    "https://web1.mbt.lt/prod/api/v1/teams/{2}/games?season_id={1}&league_id={0}",
    "https://web1.mbt.lt/prod/api/leagues/{0}/seasons/{1}/teams/{2}/games.json",
    "https://web2.mbt.lt/prod/api/v1/leagues/{0}/seasons/{1}/teams/{2}/games",
]

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
    venue = (
        g.get("arena") or g.get("arena_name") or g.get("venue") or
        g.get("location") or g.get("court") or ""
    )
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
        for key in ["games", "data", "matches", "results", "items", "schedule"]:
            if key in data and isinstance(data[key], list) and len(data[key]) > 0:
                return data[key]
    return []

def fetch_team_via_api(page, team):
    """
    Kallar beint á MBT API endapunktana í gegnum Playwright
    sem keyrir með kki.is context (réttir Origin/Referer hausar).
    """
    lid = team["league_id"]
    sid = team["season_id"]
    tid = team["team_id"]

    for url_template in MBT_URLS:
        url = url_template.format(lid, sid, tid)
        print(f"    Reyni: {url}")
        try:
            # Notum Playwright til að gera fetch() köll með kki.is origin
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
                        if (!resp.ok) return { ok: false, status: resp.status };
                        const text = await resp.text();
                        return { ok: true, status: resp.status, body: text };
                    } catch(e) {
                        return { ok: false, error: e.message };
                    }
                }
            """, url)

            if not result.get("ok"):
                print(f"      → Villa: HTTP {result.get('status')} / {result.get('error', '')}")
                continue

            body = result.get("body", "")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                print(f"      → Ekki JSON svar")
                continue

            games = extract_games(data)
            if games:
                print(f"      ✓ Fann {len(games)} leiki!")
                normalized = [normalize_game(g) for g in games]
                return [g for g in normalized if g is not None]
            else:
                print(f"      → JSON en engin leikjalisti")

        except Exception as e:
            print(f"      → Villa: {e}")

    return []

def fetch_team_via_page(page, team):
    """
    Varalausn: Hlerar API-köll þegar KKÍ síðan hleðst.
    Notar route interception til að fanga MBT beiðnir.
    """
    url = kki_url(team)
    captured = []

    def handle_route(route):
        req_url = route.request.url
        if "mbt.lt" in req_url:
            # Leyfum beiðnina en skráum hana
            captured.append(req_url)
        route.continue_()

    page.route("**/*", handle_route)

    print(f"    Hlera API köll á: {url[:60]}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(8000)  # Bíðum eftir async köllum
    except PlaywrightTimeout:
        print(f"    ⚠ Timeout")
    except Exception as e:
        print(f"    ⚠ {e}")

    page.unroute("**/*")

    if captured:
        print(f"    Fann {len(captured)} MBT beiðnir:")
        for u in captured:
            print(f"      {u}")
    else:
        print(f"    Engar MBT beiðnir fundust")

    return [], captured

def main():
    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "teams": [],
        "debug": []
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-web-security"]
        )

        # Context sem líkist kki.is umhverfi
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            extra_http_headers={
                "Accept-Language": "is-IS,is;q=0.9,en;q=0.8",
                "Origin": "https://kki.is",
                "Referer": "https://kki.is/",
            }
        )
        page = context.new_page()

        # Förum fyrst á kki.is til að setja upp rétt session/cookies
        print("Hleð kki.is forsíðu...")
        try:
            page.goto("https://kki.is", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)
            print("  ✓ kki.is hlaðið")
        except Exception as e:
            print(f"  ⚠ {e}")

        for i, team in enumerate(TEAMS):
            print(f"\n[{i+1}/{len(TEAMS)}] {team['name']}")

            # Reynum beint API köll fyrst
            games = fetch_team_via_api(page, team)

            # Ef ekkert — reynum að hlera síðuna
            if not games:
                print(f"    Reyni hlustun á síðu...")
                games, mbt_urls = fetch_team_via_page(page, team)
                if mbt_urls:
                    output["debug"].append({
                        "team": team["key"],
                        "mbt_urls": mbt_urls
                    })

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
    print(f"\n{'='*50}")
    print(f"Uppfært: {output['updated']}")
    total = 0
    for t in output["teams"]:
        n = len(t["games"])
        total += n
        status = "✓" if n > 0 else "✗"
        print(f"  {status} {t['name']}: {n} leikir")
    print(f"  Samtals: {total} leikir")

    if output["debug"]:
        print(f"\nMBT slóðir sem fundust (til frekari greiningar):")
        for d in output["debug"]:
            for u in d["mbt_urls"]:
                print(f"  {d['team']}: {u}")

    print(f"{'='*50}")

if __name__ == "__main__":
    main()
