import json
from datetime import datetime
from urllib.request import urlopen
from zoneinfo import ZoneInfo

# ============================================
# CONFIG
# ============================================

MLB_TZ = ZoneInfo("America/New_York")
NOW = datetime.now(MLB_TZ)
TODAY = NOW.date().isoformat()

BASE = "https://statsapi.mlb.com/api/v1"

# ============================================
# HELPERS
# ============================================

def fetch(url):
    with urlopen(url) as r:
        return json.loads(r.read().decode("utf-8"))

def get_pitcher_hand(person_id):
    try:
        p = fetch(f"{BASE}/people/{person_id}")
        return p["people"][0].get("pitchHand", {}).get("code", "N/A")
    except:
        return "N/A"

def get_depth_chart_hitters(team_id, pitcher_hand):
    try:
        charts = fetch(f"{BASE}/teams/{team_id}/depthCharts")
        side = "vsRHP" if pitcher_hand == "R" else "vsLHP"
        hitters = []
        positions = charts.get(side, {}).get("positions", {})
        for pos in positions.values():
            for player in pos:
                hitters.append(player["person"]["fullName"])
        return hitters[:6]
    except:
        return []

def get_official_lineup(game_pk, side):
    try:
        box = fetch(f"{BASE}/game/{game_pk}/boxscore")
        return [
            box["teams"][side]["players"][pid]["person"]["fullName"]
            for pid in box["teams"][side]["battingOrder"]
        ]
    except:
        return None

# ============================================
# LOAD SCHEDULE — NO TIME FILTER
# ============================================

schedule = fetch(
    f"{BASE}/schedule?sportId=1&date={TODAY}&hydrate=probablePitcher"
)

games = []

for day in schedule.get("dates", []):
    for g in day.get("games", []):

        away = g["teams"]["away"]
        home = g["teams"]["home"]

        away_prob = away.get("probablePitcher")
        home_prob = home.get("probablePitcher")

        def pitcher_block(prob, opponent, side):
            if not prob:
                return {
                    "name": "TBD",
                    "hand": "N/A",
                    "status": "monitor",
                    "lineup_type": "unknown",
                    "hitters": []
                }

            hand = get_pitcher_hand(prob["id"])

            official = get_official_lineup(g["gamePk"], side)
            if official:
                return {
                    "name": prob["fullName"],
                    "hand": hand,
                    "status": "confirmed",
                    "lineup_type": "official",
                    "hitters": official
                }

            return {
                "name": prob["fullName"],
                "hand": hand,
                "status": "confirmed",
                "lineup_type": "projected",
                "hitters": get_depth_chart_hitters(
                    opponent["team"]["id"], hand
                )
            }

        games.append({
            "start_time": g["gameDate"],
            "venue": g["venue"]["name"],
            "away_team": away["team"]["name"],
            "home_team": home["team"]["name"],

            "away_pitcher": pitcher_block(away_prob, home, "away"),
            "home_pitcher": pitcher_block(home_prob, away, "home")
        })

# ============================================
# WRITE OUTPUT
# ============================================

with open("daily.json", "w") as f:
    json.dump({
        "generated_at": NOW.isoformat(),
        "games": games,
        "disclaimer": (
            "Projected lineups are based on MLB depth charts and everyday starters. "
            "They are automatically replaced with official batting orders when MLB "
            "publishes game boxscores."
        )
    }, f, indent=2)
