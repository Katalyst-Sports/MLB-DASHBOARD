import json
from datetime import datetime, timedelta
from urllib.request import urlopen
from zoneinfo import ZoneInfo

MLB_TZ = ZoneInfo("America/New_York")
NOW = datetime.now(MLB_TZ)
SEASON = NOW.year

def fetch(url):
    with urlopen(url) as r:
        return json.loads(r.read().decode("utf-8"))

def hours_until(start_time):
    game_time = datetime.fromisoformat(start_time.replace("Z","")).astimezone(MLB_TZ)
    return (game_time - NOW).total_seconds() / 3600

def get_depth_chart_hitters(team_id, pitcher_hand):
    data = fetch(f"https://statsapi.mlb.com/api/v1/teams/{team_id}/depthCharts")
    hitters = []

    for side in ("vsRHP", "vsLHP"):
        if (pitcher_hand == "R" and side == "vsRHP") or \
           (pitcher_hand == "L" and side == "vsLHP"):
            for pos in data.get(side, {}).get("positions", {}).values():
                for p in pos:
                    hitters.append(p["person"]["fullName"])
    return hitters[:6]

def get_official_lineup(game_pk, team_side):
    try:
        data = fetch(f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore")
        return [
            p["person"]["fullName"]
            for p in data["teams"][team_side]["battingOrder"]
        ]
    except:
        return None

schedule = fetch(
    f"https://statsapi.mlb.com/api/v1/schedule"
    f"?sportId=1&date={NOW.date()}&hydrate=probablePitcher"
)

games = []

for day in schedule.get("dates", []):
    for g in day.get("games", []):
        hrs = hours_until(g["gameDate"])
        if hrs > 3:
            continue

        away = g["teams"]["away"]
        home = g["teams"]["home"]

        away_p = away.get("probablePitcher")
        home_p = home.get("probablePitcher")

        def lineup(team, side, pitcher):
            official = get_official_lineup(g["gamePk"], side)
            if official:
                return {
                    "type": "official",
                    "hitters": official
                }
            elif pitcher:
                return {
                    "type": "projected",
                    "hitters": get_depth_chart_hitters(
                        team["team"]["id"],
                        pitcher["pitchHand"]["code"]
                    )
                }
            else:
                return {"type": "unknown", "hitters": []}

        games.append({
            "start": g["gameDate"],
            "away": away["team"]["name"],
            "home": home["team"]["name"],
            "away_pitcher": f'{away_p["fullName"]} ({away_p["pitchHand"]["code"]})' if away_p else "TBD",
            "home_pitcher": f'{home_p["fullName"]} ({home_p["pitchHand"]["code"]})' if home_p else "TBD",
            "away_lineup": lineup(away, "away", home_p),
            "home_lineup": lineup(home, "home", away_p),
        })

with open("daily.json", "w") as f:
    json.dump({
        "generated_at": NOW.isoformat(),
        "games": games,
        "disclaimer": (
            "Lineups may be official or projected using MLB depth charts. "
            "Projected lineups reflect everyday starters and are replaced "
            "once official boxscore lineups are available."
        )
    }, f, indent=2)
