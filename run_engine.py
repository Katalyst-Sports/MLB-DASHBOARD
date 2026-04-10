import json
from datetime import datetime, timedelta
from urllib.request import urlopen
from zoneinfo import ZoneInfo

MLB_TZ = ZoneInfo("America/New_York")
NOW = datetime.now(MLB_TZ)
SEASON = NOW.year

# ---------------------------
# Helpers
# ---------------------------

def fetch(url):
    with urlopen(url) as r:
        return json.loads(r.read().decode("utf-8"))

def get_pitcher_hand(person_id):
    """
    Fetch pitcher handedness from the PEOPLE endpoint
    (schedule endpoint is unreliable for this)
    """
    try:
        data = fetch(f"https://statsapi.mlb.com/api/v1/people/{person_id}")
        return data["people"][0].get("pitchHand", {}).get("code", "N/A")
    except Exception:
        return "N/A"

def hours_until(start_time):
    game_time = datetime.fromisoformat(start_time.replace("Z", "")).astimezone(MLB_TZ)
    return (game_time - NOW).total_seconds() / 3600

def get_depth_chart_hitters(team_id, pitcher_hand):
    """
    Uses MLB depth charts to approximate everyday starters vs handedness.
    This is only used BEFORE official lineups are available.
    """
    try:
        data = fetch(f"https://statsapi.mlb.com/api/v1/teams/{team_id}/depthCharts")
        side = "vsRHP" if pitcher_hand == "R" else "vsLHP"
        hitters = []
        positions = data.get(side, {}).get("positions", {})
        for pos in positions.values():
            for player in pos:
                hitters.append(player["person"]["fullName"])
        return hitters[:6]
    except Exception:
        return []

def get_official_lineup(game_pk, side):
    """
    Returns official batting order when MLB lineups are published
    """
    try:
        data = fetch(f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore")
        return [
            data["teams"][side]["players"][pid]["person"]["fullName"]
            for pid in data["teams"][side]["battingOrder"]
        ]
    except Exception:
        return None

# ---------------------------
# Load schedule
# ---------------------------

schedule = fetch(
    f"https://statsapi.mlb.com/api/v1/schedule"
    f"?sportId=1&date={NOW.date()}&hydrate=probablePitcher"
)

games = []

# ---------------------------
# Process games (≤3 hours to start)
# ---------------------------

for day in schedule.get("dates", []):
    for g in day.get("games", []):

        if hours_until(g["gameDate"]) > 3:
            continue

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
                    opponent["team"]["id"],
                    hand
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

# ---------------------------
# Output
# ---------------------------

with open("daily.json", "w") as f:
    json.dump({
        "generated_at": NOW.isoformat(),
        "games": games,
        "disclaimer": (
            "Lineups may be official or projected using MLB depth charts. "
            "Projected lineups reflect everyday starters and are replaced automatically "
            "once official MLB boxscore lineups are available."
        )
    }, f, indent=2)
``
