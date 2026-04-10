import json
from datetime import datetime
from urllib.request import urlopen
from zoneinfo import ZoneInfo

MLB_TZ = ZoneInfo("America/New_York")
NOW = datetime.now(MLB_TZ)
TODAY = NOW.date().isoformat()
SEASON = NOW.year

BASE = "https://statsapi.mlb.com/api/v1"

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def fetch(url):
    with urlopen(url) as r:
        return json.loads(r.read().decode("utf-8"))

def get_pitcher_hand(pid):
    try:
        p = fetch(f"{BASE}/people/{pid}")
        return p["people"][0]["pitchHand"]["code"]
    except:
        return "N/A"

def pitcher_last5(pid):
    try:
        logs = fetch(
            f"{BASE}/people/{pid}/stats"
            f"?stats=gameLog&group=pitching&season={SEASON}"
        )["stats"][0]["splits"][:5]

        outs = k = bb = 0
        for g in logs:
            ip = g["stat"].get("inningsPitched", "0")
            if "." in ip:
                whole, frac = ip.split(".")
                outs += int(whole) * 3 + int(frac)
            else:
                outs += int(ip) * 3

            k += int(g["stat"].get("strikeOuts", 0))
            bb += int(g["stat"].get("baseOnBalls", 0))

        return {
            "starts": len(logs),
            "total_outs": outs,
            "avg_ip": round((outs / 3) / len(logs), 2) if logs else 0,
            "total_k": k,
            "avg_k": round(k / len(logs), 2) if logs else 0,
            "total_bb": bb,
            "avg_bb": round(bb / len(logs), 2) if logs else 0
        }
    except:
        return None

def pitcher_era(pid):
    try:
        s = fetch(
            f"{BASE}/people/{pid}/stats"
            f"?stats=season&group=pitching&season={SEASON}"
        )
        return s["stats"][0]["splits"][0]["stat"]["era"]
    except:
        return "N/A"

def hitter_last10_vs_hand(pid, hand):
    sit = "vr" if hand == "R" else "vl"
    try:
        s = fetch(
            f"{BASE}/people/{pid}/stats"
            f"?stats=statSplits&group=hitting"
            f"&sitCodes={sit}&season={SEASON}"
        )["stats"][0]["splits"]

        if not s:
            return None

        st = s[0]["stat"]
        pa = int(st.get("plateAppearances", 0))
        if pa < 10:
            return None

        hits = int(st.get("hits", 0))
        ab = int(st.get("atBats", 0))

        return {
            "pa": pa,
            "hits": hits,
            "avg": st.get("avg", "N/A")
        }
    except:
        return None

# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

schedule = fetch(
    f"{BASE}/schedule?sportId=1&date={TODAY}&hydrate=probablePitcher"
)

games = []

for d in schedule.get("dates", []):
    for g in d.get("games", []):

        away = g["teams"]["away"]["team"]
        home = g["teams"]["home"]["team"]

        away_p = g["teams"]["away"].get("probablePitcher")
        home_p = g["teams"]["home"].get("probablePitcher")

        def pitcher_block(prob):
            if not prob:
                return {"status": "monitor"}

            hand = get_pitcher_hand(prob["id"])
            return {
                "name": prob["fullName"],
                "hand": hand,
                "era": pitcher_era(prob["id"]),
                "last5": pitcher_last5(prob["id"]),
                "status": "confirmed"
            }

        games.append({
            "start_time": g["gameDate"],
            "venue": g["venue"]["name"],
            "away_team": away["name"],
            "home_team": home["name"],
            "away_pitcher": pitcher_block(away_p),
            "home_pitcher": pitcher_block(home_p)
        })

with open("daily.json", "w") as f:
    json.dump({
        "generated_at": NOW.isoformat(),
        "games": games,
        "disclaimer": (
            "All statistics shown are descriptive and historical. "
            "Small samples are directional only and not predictive."
        )
    }, f, indent=2)
