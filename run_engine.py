import json
from datetime import datetime
from urllib.request import urlopen
from zoneinfo import ZoneInfo

BASE = "https://statsapi.mlb.com/api"
MLB_TZ = ZoneInfo("America/New_York")
NOW = datetime.now(MLB_TZ)
TODAY = NOW.date().isoformat()

# -------------------------------------------------
# HELPERS
# -------------------------------------------------

def fetch(url):
    with urlopen(url) as r:
        return json.loads(r.read().decode("utf-8"))

def live_games_today():
    sched = fetch(f"{BASE}/v1/schedule?sportId=1&date={TODAY}")
    games = []
    for d in sched.get("dates", []):
        for g in d.get("games", []):
            if g["status"]["abstractGameState"] == "Live":
                games.append(g["gamePk"])
    return games

def parse_live_game(gamePk):
    live = fetch(f"{BASE}/v1.1/game/{gamePk}/feed/live")
    box = live["liveData"]["boxscore"]
    status = live["gameData"]["status"]["detailedState"]
    linescore = live["liveData"]["linescore"]

    gamesum = {
        "gamePk": gamePk,
        "status": status,
        "inning": linescore.get("currentInningOrdinal"),
        "score": f'{linescore["teams"]["away"]["runs"]} - {linescore["teams"]["home"]["runs"]}',
        "hot_hitters": [],
        "top_pitchers": [],
        "bullpen_active": False
    }

    for side in ["away", "home"]:
        pitchers = box["teams"][side]["pitchers"]
        players = box["teams"][side]["players"]

        starter = pitchers[0] if pitchers else None
        current = pitchers[-1] if pitchers else None

        if starter != current:
            gamesum["bullpen_active"] = True

        for pid in pitchers:
            p = players[f"ID{pid}"]["stats"]["pitching"]
            if p.get("strikeOuts", 0) >= 6 and p.get("earnedRuns", 0) <= 2:
                gamesum["top_pitchers"].append({
                    "name": players[f"ID{pid}"]["person"]["fullName"],
                    "k": p["strikeOuts"],
                    "er": p["earnedRuns"]
                })

        for bid in box["teams"][side]["batters"]:
            b = players[f"ID{bid}"]["stats"]["batting"]
            tb = b.get("hits", 0) + b.get("doubles", 0) + (2 * b.get("triples", 0)) + (3 * b.get("homeRuns", 0))
            if b.get("hits", 0) >= 2 or tb >= 3:
                gamesum["hot_hitters"].append({
                    "name": players[f"ID{bid}"]["person"]["fullName"],
                    "hits": b.get("hits"),
                    "tb": tb
                })

    return gamesum

# -------------------------------------------------
# MAIN EXECUTION
# -------------------------------------------------

live_ids = live_games_today()
live_data = []

for gid in live_ids:
    live_data.append(parse_live_game(gid))

with open("live.json", "w") as f:
    json.dump({
        "updated_at": NOW.isoformat(),
        "games": live_data,
        "disclaimer": (
            "Live stats are descriptive only and reflect in‑game results as reported by MLB."
        )
    }, f, indent=2)
