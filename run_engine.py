import json
from datetime import datetime
from urllib.request import urlopen
from zoneinfo import ZoneInfo

# =====================================================
# CONFIG
# =====================================================

BASE = "https://statsapi.mlb.com/api"
MLB_TZ = ZoneInfo("America/New_York")
NOW = datetime.now(MLB_TZ)
TODAY = NOW.date().isoformat()
SEASON = NOW.year

# =====================================================
# UTILS
# =====================================================

def fetch(url):
    with urlopen(url) as r:
        return json.loads(r.read().decode("utf-8"))

def n(x):
    return x if x is not None else 0

# =====================================================
# PITCHER FUNCTIONS (SAFE)
# =====================================================

def pitcher_hand(pid):
    try:
        return fetch(f"{BASE}/v1/people/{pid}")["people"][0]["pitchHand"]["code"]
    except Exception:
        return "N/A"

def pitcher_era(pid):
    try:
        return fetch(
            f"{BASE}/v1/people/{pid}/stats"
            f"?stats=season&group=pitching&season={SEASON}"
        )["stats"][0]["splits"][0]["stat"].get("era", "N/A")
    except Exception:
        return "N/A"

def pitcher_last5(pid):
    """
    Bulletproof last‑5 start processing.
    Handles missing logs, openers, rookies, empty API payloads.
    NEVER crashes.
    """
    try:
        data = fetch(
            f"{BASE}/v1/people/{pid}/stats"
            f"?stats=gameLog&group=pitching&season={SEASON}"
        )

        if not data.get("stats"):
            raise ValueError("No stats")

        splits = data["stats"][0].get("splits", [])
        if not splits:
            raise ValueError("No game logs")

        logs = splits[:5]

        ip = k = bb = h = er = 0.0

        for g in logs:
            ip_raw = g["stat"].get("inningsPitched", "0")

            if "." in ip_raw:
                whole, frac = ip_raw.split(".")
                ip += int(whole) + int(frac) / 3
            else:
                ip += float(ip_raw)

            k  += int(g["stat"].get("strikeOuts", 0))
            bb += int(g["stat"].get("baseOnBalls", 0))
            h  += int(g["stat"].get("hits", 0))
            er += int(g["stat"].get("earnedRuns", 0))

        games = len(logs)
        whip = (h + bb) / ip if ip > 0 else None

        quality = games >= 1 and (ip / games) >= 6 and (er / games) <= 3
        elite = games >= 1 and (ip / games) >= 7 and (k / games) >= 8 and whip is not None and whip <= 1.00

        return {
            "avg_ip": round(ip / games, 2),
            "avg_k": round(k / games, 2),
            "avg_bb": round(bb / games, 2),
            "whip": round(whip, 2) if whip is not None else "N/A",
            "quality": quality,
            "elite": elite
        }

    except Exception:
        # SAFE FALLBACK
        return {
            "avg_ip": "N/A",
            "avg_k": "N/A",
            "avg_bb": "N/A",
            "whip": "N/A",
            "quality": False,
            "elite": False
        }

# =====================================================
# HITTER FUNCTIONS
# =====================================================

def hitter_season_stats(pid):
    try:
        s = fetch(
            f"{BASE}/v1/people/{pid}/stats"
            f"?stats=season&group=hitting&season={SEASON}"
        )["stats"][0]["splits"][0]["stat"]

        ab = n(s.get("atBats"))
        so = n(s.get("strikeOuts"))
        bb = n(s.get("baseOnBalls"))
        hr = n(s.get("homeRuns"))
        avg = s.get("avg", "N/A")

        pa = ab + bb
        bip = ab - so - hr
        bip_pa = round(bip / pa, 2) if pa > 0 else "N/A"

        return {
            "avg": avg,
            "k_rate": round((so / pa) * 100, 1) if pa else None,
            "bb_rate": round((bb / pa) * 100, 1) if pa else None,
            "bip_pa": bip_pa,
            "so": so,
            "bb": bb
        }

    except Exception:
        return {
            "avg": "N/A",
            "k_rate": "N/A",
            "bb_rate": "N/A",
            "bip_pa": "N/A",
            "so": 0,
            "bb": 0
        }

def batting_order_tier(stats):
    try:
        if stats["avg"] != "N/A" and float(stats["avg"]) >= 0.285 and stats["k_rate"] <= 18:
            return "Top‑Order"
        if stats["k_rate"] is not None and stats["k_rate"] <= 25:
            return "Middle‑Order"
        return "Bottom‑Order"
    except Exception:
        return "Bottom‑Order"

def hit_streak(pid):
    try:
        logs = fetch(
            f"{BASE}/v1/people/{pid}/stats"
            f"?stats=gameLog&group=hitting&season={SEASON}"
        )["stats"][0]["splits"]

        streak = 0
        for g in logs:
            if n(g["stat"].get("hits")) > 0:
                streak += 1
            else:
                break
        return streak
    except Exception:
        return 0

def risp_stats(pid):
    try:
        s = fetch(
            f"{BASE}/v1/people/{pid}/stats"
            f"?stats=season&group=hitting&sitCodes=risp&season={SEASON}"
        )["stats"][0]["splits"][0]["stat"]

        return {
            "avg": s.get("avg", "N/A"),
            "hits": s.get("hits", "N/A")
        }
    except Exception:
        return {"avg": "N/A", "hits": "N/A"}

# =====================================================
# TEAM ROSTER
# =====================================================

def team_hitters(team_id):
    try:
        roster = fetch(f"{BASE}/v1/teams/{team_id}/roster")["roster"]
        return [
            {"id": p["person"]["id"], "name": p["person"]["fullName"]}
            for p in roster if p["position"]["type"] != "Pitcher"
        ][:9]
    except Exception:
        return []

# =====================================================
# DAILY BUILD
# =====================================================

schedule = fetch(
    f"{BASE}/v1/schedule?sportId=1&date={TODAY}&hydrate=probablePitcher"
)

daily_games = []

for d in schedule.get("dates", []):
    for g in d.get("games", []):

        away = g["teams"]["away"]["team"]
        home = g["teams"]["home"]["team"]

        ap = g["teams"]["away"].get("probablePitcher")
        hp = g["teams"]["home"].get("probablePitcher")

        game = {
            "away_team": away["name"],
            "home_team": home["name"],
            "venue": g["venue"]["name"],
            "start": g["gameDate"],
            "away_pitcher": {},
            "home_pitcher": {},
            "away_hitters": [],
            "home_hitters": []
        }

        if ap:
            game["away_pitcher"] = {
                "name": ap["fullName"],
                "hand": pitcher_hand(ap["id"]),
                "era": pitcher_era(ap["id"]),
                **pitcher_last5(ap["id"])
            }

        if hp:
            game["home_pitcher"] = {
                "name": hp["fullName"],
                "hand": pitcher_hand(hp["id"]),
                "era": pitcher_era(hp["id"]),
                **pitcher_last5(hp["id"])
            }

        for side, team in [("away_hitters", away), ("home_hitters", home)]:
            for h in team_hitters(team["id"]):
                stats = hitter_season_stats(h["id"])
                game[side].append({
                    "name": h["name"],
                    "tier": batting_order_tier(stats),
                    "stats": stats,
                    "streak": hit_streak(h["id"]),
                    "risp": risp_stats(h["id"])
                })

        daily_games.append(game)

# =====================================================
# OUTPUT
# =====================================================

with open("daily.json", "w") as f:
    json.dump(
        {"updated_at": NOW.isoformat(), "games": daily_games},
        f,
        indent=2
    )
