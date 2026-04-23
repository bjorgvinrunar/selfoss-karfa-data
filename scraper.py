#!/usr/bin/env python3
"""
Selfoss Körfubolti — KKÍ gagnasækir
Notar Playwright til að opna KKÍ síðurnar og sækja leikjagögn.
Vistar niðurstöðurnar í data/games.json
"""

import json
import os
import sys
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

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

def scrape_team(page, team):
    """Sækir leikjagögn fyrir eitt lið með því að hlera API-köll."""
    url = kki_url(team)
    games = []
    api_responses = []

    # Hlera öll network response sem líta út eins og leikjagögn
    def handle_response(response):
        try:
            req_url = response.url
            if "mbt.lt" in req_url or ("kki.is" in req_url and any(
                x in req_url for x in ["game", "match", "season", "league"]
            )):
                if response.status == 200:
                    try:
                        data = response.json()
                        api_responses.append({"url": req_url, "data": data})
                        print(f"  → API svar: {req_url[:80]}")
                    except Exception:
                        pass
        except Exception:
            pass

    page.on("response", handle_response)

    print(f"Sæki: {team['name']} — {url}")
    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
    except Exception as e:
        print(f"  Villa við hlöðun: {e}")

    page.off("response", handle_response)

    # Leitum að leikjagögnum í API svörunum
    for resp in api_responses:
        data = resp["data"]
        candidates = []

        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            for key in ["games", "data", "matches", "results", "items"]:
                if key in data and isinstance(data[key], list):
                    candidates = data[key]
                    break

        if candidates:
            games = candidates
            print(f"  ✓ Fann {len(games)} leiki í {resp['url'][:60]}")
            break

    if not games:
        print(f"  ✗ Engin API gögn fundust — reyni að lesa úr DOM")
        games = scrape_dom(page, team)

    return games

def scrape_dom(page, team):
    """
    Varalausn: reynir að lesa leikjagögn beint úr DOM-inum
    ef API hlustun skilaði engu.
    """
    games = []
    try:
        # Bíðum eftir að leikjatafla birtist
        page.wait_for_selector(".game, .match, .fixture, [class*='game'], [class*='match']",
                               timeout=5000)

        rows = page.query_selector_all(".game, .match, .fixture, [class*='game-row'], [class*='match-row']")
        print(f"  DOM: fann {len(rows)} þætti")

        for row in rows:
            text = row.inner_text()
            games.append({"raw_text": text, "source": "dom"})

    except Exception as e:
        print(f"  DOM villa: {e}")

    return games

def normalize_game(g):
    """Normalíserar leikjafærslu úr mismunandi API sniðum."""
    # Dagsetning
    date_str = (
        g.get("start_date") or g.get("date") or g.get("game_date") or
        g.get("start_time") or g.get("time") or g.get("gameDate") or
        g.get("startDate") or g.get("scheduled") or ""
    )

    # Lið nöfn
    home = (
        g.get("home_team_name") or
        (g.get("home_team", {}) or {}).get("name", "") or
        g.get("homeTeamName") or g.get("homeTeam") or g.get("home") or ""
    )
    away = (
        g.get("away_team_name") or
        (g.get("away_team", {}) or {}).get("name", "") or
        g.get("awayTeamName") or g.get("awayTeam") or g.get("away") or ""
    )

    # Úrslit
    sh = g.get("home_score") if g.get("home_score") is not None else g.get("homeScore")
    sa = g.get("away_score") if g.get("away_score") is not None else g.get("awayScore")

    # Staðsetning
    venue = (
        g.get("arena") or g.get("arena_name") or g.get("venue") or
        g.get("location") or g.get("court") or ""
    )

    if not date_str and not home and not away:
        return None

    return {
        "date": date_str,
        "home": str(home),
        "away": str(away),
        "home_score": sh,
        "away_score": sa,
        "venue": str(venue),
    }

def main():
    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "teams": []
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            extra_http_headers={
                "Accept-Language": "is-IS,is;q=0.9,en;q=0.8",
            }
        )
        page = context.new_page()

        for team in TEAMS:
            games_raw = scrape_team(page, team)
            games = []
            for g in games_raw:
                if "raw_text" in g:
                    # DOM scrape — geysum hrá texta til frekari greiningar
                    games.append(g)
                else:
                    n = normalize_game(g)
                    if n:
                        games.append(n)

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
            print(f"  → {len(games)} leikir vistaðir\n")

        browser.close()

    # Vista JSON
    os.makedirs("data", exist_ok=True)
    with open("data/games.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Gögn vistuð í data/games.json")
    print(f"  Uppfært: {output['updated']}")

    # Prentum yfirlit
    for t in output["teams"]:
        print(f"  {t['name']}: {len(t['games'])} leikir")

    # Skilum villu ef engin gögn fundust (til að GitHub Actions geti greint vandann)
    total = sum(len(t["games"]) for t in output["teams"])
    if total == 0:
        print("\n⚠ AÐVÖRUN: Engin gögn fundust!")
        sys.exit(1)

if __name__ == "__main__":
    main()
