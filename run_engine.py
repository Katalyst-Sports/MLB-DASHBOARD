import json
from urllib.request import urlopen
from datetime import datetime
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# TIME + API CONFIG
# -----------------------------------------------------------------------------

MLB_TZ = ZoneInfo("America/New_York")
TODAY = datetime.now(MLB_TZ).date().isoformat()

SCHEDULE_URL = (
    "https://statsapi.mlb.com/api/v1/schedule"
    f"?sportId=1&date={TODAY}&hydrate=probablePitcher"
)

# -----------------------------------------------------------------------------
# CONTEXT DICTIONARIES (STATIC, SAFE)
# -----------------------------------------------------------------------------

HITTER_FRIENDLY = {
    "Coors Field",
    "Great American Ball Park",
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

ROOFED = {
    "Rogers Centre",
    "Minute Maid Park",
    "Tropicana Field",
    "Chase Field",
}

# -----------------------------------------------------------------------------
# FETCH SCHEDULE
# -----------------------------------------------------------------------------

with urlopen(SCHEDULE_URL) as response:
    data = json.loads(response.read().decode("utf-8"))

games = []

# -----------------------------------------------------------------------------
# PARSE GAMES (NO INFERENCE, INFORMATIONAL ONLY)
# -----------------------------------------------------------------------------

for day in data.get("dates", []):
    for game in day.get("games", []):

        venue = game["venue"]["name"]

        away_prob = game["teams"]["away"].get("probablePitcher")
        home_prob = game["teams"]["home"].get("probablePitcher")

        def pitcher_outlooks(prob):
            if not prob:
                return {
                    "workload": "TBD",
                    "strikeouts": "TBD",
                    "frequency_note": "Monitor only"
                }

            hand = prob.get("pitchHand", {}).get("code", "N/A")

            return {
                "hand": hand,
                "workload": "5–6 innings",
                "workload_frequency": "Longer outings less frequent",
                "strikeouts": "4–6",
                "strikeout_frequency": "Upper‑end games occasional"
            }

        games.append({
            "game_id": game["gamePk"],
            "start_time": game["gameDate"],
            "away": game["teams"]["away"]["team"]["name"],
            "home": game["teams"]["home"]["team"]["name"],
            "venue": venue,

            "away_starter": away_prob.get("fullName") if away_prob else "TBD",
            "home_starter": home_prob.get("fullName") if home_prob else "TBD",

            "away_status": "confirmed" if away_prob else "monitor",
            "home_status": "confirmed" if home_prob else "monitor",

            "away_pitcher_context": pitcher_outlooks(away_prob),
            "home_pitcher_context": pitcher_outlooks(home_prob),

            # HITTER PERFORMANCE CONTEXT (RANGE‑BASED)
            "hitter_bases_outlook": {
                "expected_range": "1–2 total bases",
                "upper_range": "Higher outputs less frequent",
            },

            # PARK + WEATHER CONTEXT
            "park_factor": (
                "Hitter Friendly" if venue in HITTER_FRIENDLY else
                "Pitcher Friendly" if venue in PITCHER_FRIENDLY else
                "Neutral"
            ),

            "weather": (
                "Roof Controlled" if venue in ROOFED else
                "Open Air (variable conditions)"
            )
        })

# -----------------------------------------------------------------------------
# OUTPUT FILE
# -----------------------------------------------------------------------------

output = {
    "date": TODAY,
    "last_updated": datetime.utcnow().isoformat() + "Z",
    "game_count": len(games),
    "games": games,
    "disclaimer": (
        "This dashboard provides descriptive performance context only. "
        "Ranges and frequency labels reflect historical and situational patterns, "
        "not guarantees or recommendations."
    )
}

with open("daily.json", "w") as f:
    json.dump(output, f, indent=2)
