import json
from urllib.request import urlopen
from datetime import datetime
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

# MLB schedules are defined by US Eastern Time, NOT UTC.
# GitHub Actions runs in UTC, so we must normalize correctly.
MLB_TIMEZONE = ZoneInfo("America/New_York")

TODAY = datetime.now(MLB_TIMEZONE).date().isoformat()

# MLB Stats API endpoint
# hydrate=probablePitcher attaches starters when MLB has posted them
SCHEDULE_URL = (
    "https://statsapi.mlb.com/api/v1/schedule"
    f"?sportId=1&date={TODAY}&hydrate=probablePitcher"
)

# -----------------------------------------------------------------------------
# FETCH MLB SCHEDULE
# -----------------------------------------------------------------------------

with urlopen(SCHEDULE_URL) as response:
    data = json.loads(response.read().decode("utf-8"))

games = []

# -----------------------------------------------------------------------------
# PARSE GAMES SAFELY (NEVER DROP A GAME)
# -----------------------------------------------------------------------------

for day in data.get("dates", []):
    for game in day.get("games", []):

        # Team names
        away_team = game["teams"]["away"]["team"]["name"]
        home_team = game["teams"]["home"]["team"]["name"]

        # Probable starters (only if MLB provides them)
        away_pitcher = game["teams"]["away"].get("probablePitcher", {}).get("fullName")
        home_pitcher = game["teams"]["home"].get("probablePitcher", {}).get("fullName")

        games.append({
            "game_id": game["gamePk"],
            "start_time": game["gameDate"],
            "away": away_team,
            "home": home_team,
            "venue": game["venue"]["name"],

            # Do NOT infer starters — only show MLB-provided probables
            "away_starter": away_pitcher or "TBD",
            "home_starter": home_pitcher or "TBD"
        })

# -----------------------------------------------------------------------------
# OUTPUT PAYLOAD
# -----------------------------------------------------------------------------

output = {
    "date": TODAY,
    "last_updated": datetime.utcnow().isoformat() + "Z",
    "game_count": len(games),   # sanity check indicator
    "games": games,

    "disclaimer": (
        "This dashboard is provided for informational and educational purposes only. "
        "The information displayed may be inaccurate or change at any time. "
        "MLB schedules and starting pitchers are subject to change without notice. "
        "This does not constitute gambling, betting, or financial advice. "
        "Use at your own risk."
    )
}

# -----------------------------------------------------------------------------
# WRITE FILE FOR DASHBOARD
# -----------------------------------------------------------------------------

with open("daily.json", "w") as f:
    json.dump(output, f, indent=2)
``
