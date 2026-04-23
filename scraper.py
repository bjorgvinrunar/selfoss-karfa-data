#!/usr/bin/env python3
"""
Selfoss Körfubolti — KKÍ gagnasækir
Hlerar API-köll þegar KKÍ síðan hleðst í Playwright.
"""

import json
import os
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
        (home_team.get("name") if isinstance(home_team, dict) else home_team) or
        g.get("homeTeamName") or g.get("homeTeam") or g.get("home") or ""
    )
    away = (
        g.get("away_team_name") or
        (away_team.get("name") if isinstance(away_team, dict) else away_team) or
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

def extract_games_from_data(data):
    """Finnur leikjalista úr mismunandi API sniðum."""
    if isinstance(data, list) and len(data) > 0:
        return data
    if isinstance(data, dict):
        for key in ["games", "data", "matches", "results", "items", "schedule"]:
            if key in data and isinstance(data[key], list):
                return data[key]
    return []

def scrape_team(page, team):
    """Hlerar API-köll þegar KKÍ síðan hleðst."""
    url = kki_url(team)
    api_responses = []

    def handle_response(response):
        try:
            req_url = response.url
            # Hlustum á MBT og KKÍ API köll
            if "mbt.lt" in req_url or (
                "kki.is" in req_url and
                any(x in req_url.lower() for x in ["game", "match", "season", "league", "team", "json", "api"])
            ):
                if response.status == 200:
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type or "javascript" in content_type:
                        try:
                            data = response.json()
                            games = extract_games_from_data(data)
                            if games:
                                api_responses.append({
                                    "url": req_url,
                                    "games": games
                                })
                                print(f"    ✓ API: {req_url[:70]} → {len(games)} leikir")
                        except Exception:
                            pass
        except Exception:
            pass

    # Setjum upp hlustara áður en við förum á síðuna
    page.on("response", handle_response)

    print(f"  Sæki: {url[:80]}")
    try:
        # Prófum fyrst með styttri timeout og "load" í stað "networkidle"
        page.goto(url, wait_until="load", timeout=20000)
        # Bíðum aðeins til að JavaScript klárist
        page.wait_for_timeout(5000)
    except PlaywrightTimeout:
        print(f"    ⚠ Timeout — reyni að nota það sem hlustað var")
    except Exception as e:
        print(f"    ⚠ Villa: {e}")

    # Fjarlægjum hlustara (rétt API — route í stað .off)
    try:
        page.remove_listener("response", handle_response)
    except Exception:
        pass

    # Finnum bestu gögnin
    best_games = []
    for resp in api_responses:
        if len(resp["games"]) > len(best_games):
            best_games = resp["games"]

    if best_games:
        normalized = [normalize_game(g) for g in best_games]
        normalized = [g for g in normalized if g is not None]
        print(f"    → {len(normalized)} leikir normalisaðir")
        return normalized

    print(f"    ✗ Engin gögn fundust")
    return []

def main():
    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "teams": []
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            extra_http_headers={"Accept-Language": "is-IS,is;q=0.9,en;q=0.8"}
        )
        page = context.new_page()

        for i, team in enumerate(TEAMS):
            print(f"\n[{i+1}/{len(TEAMS)}] {team['name']}")
            games = scrape_team(page, team)

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
    print(f"{'='*50}")
    print("Gögn vistuð í data/games.json")

    # Skilum ekki villu þótt einhver lið hafi engin gögn
    # (við viljum alltaf uppfæra games.json jafnvel með tómum lista)

if __name__ == "__main__":
    main()
