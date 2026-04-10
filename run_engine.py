import json
from urllib.request import urlopen
from datetime import datetime
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------

MLB_TIMEZONE = ZoneInfo("America/New_York")
TODAY = datetime.now(MLB_TIMEZONE).date().isoformat()

SCHEDULE_URL = (
    "https://statsapi.mlb.com/api/v1/schedule"
    f"?sportId=1&date={TODAY}&hydrate=probablePitcher"
)

# -----------------------------------------------------------------------------
# STATIC PARK FACTOR CATEGORIES (CONSERVATIVE, NON-NUMERIC)
# -----------------------------------------------------------------------------

HITTER_FRIENDLY = {
    "Great American Ball Park",
    "Coors Field",
    "Fenway Park",
    "Yankee Stadium",
    "Citizens Bank Park",
}

PITCHER_FRIENDLY = {
    "Petco Park",
    "Oracle Park",
    "T-Mobile Park",
    "Tropicana Field",
}

ROOFED_STADIUMS = {
    "Rogers Centre",
    "Tropicana Field",
    "Chase Field",
    "Minute Maid Park",
}

# -----------------------------------------------------------------------------
# FETCH MLB SCHEDULE
# -----------------------------------------------------------------------------

with urlopen(SCHEDULE_URL) as response:
    data = json.loads(response.read().decode("utf-8"))

games = []

# -----------------------------------------------------------------------------
# PARSE GAMES (NO INFERENCE, NO DROPPING)
# -----------------------------------------------------------------------------

for day in data.get("dates", []):
    for game in day.get("games", []):

        venue = game["venue"]["name"]

        away_probable = game["teams"]["away"].get("probablePitcher")
        home_probable = game["teams"]["home"].get("probablePitcher")

        away_pitcher = away_probable.get("fullName") if away_probable else "TBD"
        home_pitcher = home_probable.get("fullName") if home_probable else "TBD"

        away_hand = away_probable.get("pitchHand", {}).get("code") if away_probable else None
        home_hand = home_probable.get("pitchHand", {}).get("code") if home_probable else None

        games.append({
            "game_id": game["gamePk"],
            "start_time": game["gameDate"],
            "away": game["teams"]["away"]["team"]["name"],
            "home": game["teams"]["home"]["team"]["name"],
            "venue": venue,

            "away_starter": away_pitcher,
            "home_starter": home_pitcher,

            "away_starter_status": "confirmed" if away_probable else "monitor",
            "home_starter_status": "confirmed" if home_probable else "monitor",

            "away_pitch_hand": away_hand or "N/A",
            "home_pitch_hand": home_hand or "N/A",

            "park_factor": (
                "Hitter Friendly" if venue in HITTER_FRIENDLY else
                "Pitcher Friendly" if venue in PITCHER_FRIENDLY else
                "Neutral"
            ),

            "weather": (
                "Roof Closed" if venue in ROOFED_STADIUMS else
                "Open Air (Weather Variable)"
            )
        })

# -----------------------------------------------------------------------------
# OUTPUT
# -----------------------------------------------------------------------------

output = {
    "date": TODAY,
    "last_updated": datetime.utcnow().isoformat() + "Z",
    "game_count": len(games),
    "games": games,
    "disclaimer": (
        "This dashboard is for informational and educational purposes only. "
        "All data reflects publicly available MLB information and may change without notice. "
        "This does not constitute gambling, betting, or financial advice."
    )
}

with open("daily.json", "w") as f:
    json.dump(output, f, indent=2)
