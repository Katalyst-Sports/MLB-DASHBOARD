import json
from urllib.request import urlopen
from zoneinfo import ZoneInfo
from datetime import datetime

TODAY = datetime.now(ZoneInfo("America/New_York")).date().isoformat()

url = (
    "https://statsapi.mlb.com/api/v1/schedule"
    f"?sportId=1&date={TODAY}"
)

with urlopen(url) as response:
    data = json.loads(response.read().decode("utf-8"))

games = []

for day in data.get("dates", []):
    for game in day.get("games", []):
        away_team = game["teams"]["away"]["team"]["name"]
        home_team = game["teams"]["home"]["team"]["name"]

        away_pitcher = game["teams"]["away"].get("probablePitcher", {}).get("fullName")
        home_pitcher = game["teams"]["home"].get("probablePitcher", {}).get("fullName")

        games.append({
            "game_id": game["gamePk"],
            "start_time": game["gameDate"],
            "away": away_team,
            "home": home_team,
            "venue": game["venue"]["name"],
            "away_starter": away_pitcher or "TBD",
            "home_starter": home_pitcher or "TBD"
        })


output = {
    "date": TODAY,
    "last_updated": datetime.utcnow().isoformat() + "Z",
    "games": games,
    "disclaimer": (
        "This dashboard is provided for informational and educational purposes only. "
        "The information displayed may be inaccurate or change without notice. "
        "This does not constitute gambling, betting, or financial advice. "
        "Use at your own risk."
    )
}

with open("daily.json", "w") as f:
    json.dump(output, f, indent=2)
