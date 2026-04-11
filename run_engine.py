import json
import os
from datetime import datetime
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from openai import OpenAI

# =====================================================
# CONFIG
# =====================================================

BASE = "https://statsapi.mlb.com/api"
MLB_TZ = ZoneInfo("America/New_York")
NOW = datetime.now(MLB_TZ)
TODAY = NOW.date().isoformat()
SEASON = NOW.year

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# =====================================================
# UTILITIES
# =====================================================

def fetch(url):
    with urlopen(url) as r:
        return json.loads(r.read().decode("utf-8"))

def n(x):
    return x if x is not None else 0

# =====================================================
# PITCHER HELPERS
# =====================================================

def pitcher_hand(pid):
    try:
        return fetch(f"{BASE}/v1/people/{pid}")["people"][0]["pitchHand"]["code"]
    except:
        return "N/A"

def pitcher_era(pid):
    try:
        return fetch(
            f"{BASE}/v1/people/{pid}/stats?stats=season&group=pitching&season={SEASON}"
        )["stats"][0]["splits"][0]["stat"].get("era", "N/A")
    except:
        return "N/A"

def pitcher_era_splits(pid):
    try:
        splits = fetch(
            f"{BASE}/v1/people/{pid}/stats"
            f"?stats=statSplits&group=pitching&season={SEASON}&sitCodes=vr,vl"
        )["stats"][0]["splits"]

        out = {"vsRHB": "N/A", "vsLHB": "N/A"}
        for s in splits:
            if s["split"]["code"] == "vr":
                out["vsRHB"] = s["stat"].get("era", "N/A")
            if s["split"]["code"] == "vl":
                out["vsLHB"] = s["stat"].get("era", "N/A")
        return out
    except:
        return {"vsRHB": "N/A", "vsLHB": "N/A"}

def pitcher_last5(pid):
    try:
        logs = fetch(
            f"{BASE}/v1/people/{pid}/stats?stats=gameLog&group=pitching&season={SEASON}"
        )["stats"][0]["splits"][:5]

        ip = k = bb = h = er = 0.0
        for g in logs:
            raw = g["stat"].get("inningsPitched", "0")
            if "." in raw:
                w, f = raw.split(".")
                ip += int(w) + int(f) / 3
            else:
                ip += float(raw)

            k += n(g["stat"].get("strikeOuts"))
            bb += n(g["stat"].get("baseOnBalls"))
            h += n(g["stat"].get("hits"))
            er += n(g["stat"].get("earnedRuns"))

        games = len(logs)
        whip = (h + bb) / ip if ip else None
        kbb = round(k / bb, 2) if bb else "∞"

        return {
            "avg_ip": round(ip / games, 2),
            "avg_k": round(k / games, 2),
            "avg_bb": round(bb / games, 2),
            "whip": round(whip, 2) if whip else "N/A",
            "k_bb": kbb,
            "command": (
                "Elite Command" if kbb == "∞" or kbb >= 4 else
                "Strong Command" if kbb >= 3 else
                "Average Command" if kbb >= 2 else
                "Below Average Command"
            ),
            "quality": ip / games >= 6 and er / games <= 3,
            "elite": ip / games >= 7 and k / games >= 8 and whip and whip <= 1.00
        }
    except:
        return {
            "avg_ip": "N/A",
            "avg_k": "N/A",
            "avg_bb": "N/A",
            "whip": "N/A",
            "k_bb": "N/A",
            "command": "N/A",
            "quality": False,
            "elite": False
        }

# =====================================================
# HITTER HELPERS
# =====================================================

def hitter_season(pid):
    try:
        s = fetch(
            f"{BASE}/v1/people/{pid}/stats?stats=season&group=hitting&season={SEASON}"
        )["stats"][0]["splits"][0]["stat"]

        ab = n(s.get("atBats"))
        so = n(s.get("strikeOuts"))
        bb = n(s.get("baseOnBalls"))
        hr = n(s.get("homeRuns"))
        pa = ab + bb
        bip = ab - so - hr

        return {
            "avg": s.get("avg", "N/A"),
            "bip_pa": round(bip / pa, 2) if pa else "N/A"
        }
    except:
        return {"avg": "N/A", "bip_pa": "N/A"}

def hitter_split_season(pid, hand):
    sit = "vr" if hand == "R" else "vl"
    try:
        s = fetch(
            f"{BASE}/v1/people/{pid}/stats"
            f"?stats=statSplits&group=hitting&season={SEASON}&sitCodes={sit}"
        )["stats"][0]["splits"][0]["stat"]
        return {"avg": s.get("avg", "N/A"), "hits": s.get("hits", "N/A")}
    except:
        return {"avg": "N/A", "hits": "N/A"}

def last10_ab(pid):
    try:
        logs = fetch(
            f"{BASE}/v1/people/{pid}/stats?stats=gameLog&group=hitting&season={SEASON}"
        )["stats"][0]["splits"]

        ab = hits = 0
        for g in logs:
            if ab >= 10:
                break
            game_ab = n(g["stat"].get("atBats"))
            game_hits = n(g["stat"].get("hits"))
            take = min(10 - ab, game_ab)
            ab += take
            hits += min(game_hits, take)

        return {"ab": ab, "hits": hits, "avg": round(hits / ab, 3) if ab else "N/A"}
    except:
        return {"ab": 0, "hits": 0, "avg": "N/A"}

def hit_streak(pid):
    try:
        logs = fetch(
            f"{BASE}/v1/people/{pid}/stats?stats=gameLog&group=hitting&season={SEASON}"
        )["stats"][0]["splits"]
        streak = 0
        for g in logs:
            if n(g["stat"].get("hits")) > 0:
                streak += 1
            else:
                break
        return streak
    except:
        return 0

def risp(pid):
    try:
        s = fetch(
            f"{BASE}/v1/people/{pid}/stats?stats=season&group=hitting&season={SEASON}&sitCodes=risp"
        )["stats"][0]["splits"][0]["stat"]
        return {"avg": s.get("avg", "N/A")}
    except:
        return {"avg": "N/A"}

def team_hitters(team_id):
    try:
        roster = fetch(f"{BASE}/v1/teams/{team_id}/roster")["roster"]
        return [
            {"id": p["person"]["id"], "name": p["person"]["fullName"]}
            for p in roster if p["position"]["type"] != "Pitcher"
        ][:9]
    except:
        return []

# =====================================================
# BUILD DAILY / LIVE / POSTGAME
# =====================================================

schedule = fetch(
    f"{BASE}/v1/schedule?sportId=1&date={TODAY}&hydrate=probablePitcher"
)

daily = []
live = []
postgame = []

for d in schedule.get("dates", []):
    for g in d.get("games", []):

        away = g["teams"]["away"]["team"]
        home = g["teams"]["home"]["team"]
        status = g["status"]["abstractGameState"]

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
                "era_splits": pitcher_era_splits(ap["id"]),
                **pitcher_last5(ap["id"])
            }

        if hp:
            game["home_pitcher"] = {
                "name": hp["fullName"],
                "hand": pitcher_hand(hp["id"]),
                "era": pitcher_era(hp["id"]),
                "era_splits": pitcher_era_splits(hp["id"]),
                **pitcher_last5(hp["id"])
            }

        for side, team in [("away_hitters", away), ("home_hitters", home)]:
            for h in team_hitters(team["id"]):
                game[side].append({
                    "name": h["name"],
                    "stats": hitter_season(h["id"]),
                    "vsRHP": hitter_split_season(h["id"], "R"),
                    "vsLHP": hitter_split_season(h["id"], "L"),
                    "last10": last10_ab(h["id"]),
                    "streak": hit_streak(h["id"]),
                    "risp": risp(h["id"])
                })

        daily.append(game)

        if status in ["Live", "In Progress"]:
            feed = fetch(f"{BASE}/v1.1/game/{g['gamePk']}/feed/live")
            lines = feed["liveData"]["linescore"]
            box = feed["liveData"]["boxscore"]

            hot = []
            dom = []

            for side in ["away", "home"]:
                for bid in box["teams"][side]["batters"]:
                    b = box["teams"][side]["players"][f"ID{bid}"]["stats"]["batting"]
                    if n(b.get("hits")) >= 2:
                        hot.append(
                            box["teams"][side]["players"][f"ID{bid}"]["person"]["fullName"]
                        )

                for pid in box["teams"][side]["pitchers"][-1:]:
                    p = box["teams"][side]["players"][f"ID{pid}"]["stats"]["pitching"]
                    if n(p.get("strikeOuts")) >= 6:
                        dom.append(
                            box["teams"][side]["players"][f"ID{pid}"]["person"]["fullName"]
                        )

            live.append({
                "game": f"{away['name']} @ {home['name']}",
                "score": f"{lines['teams']['away']['runs']}–{lines['teams']['home']['runs']}",
                "inning": lines.get("currentInningOrdinal"),
                "hot_hitters": hot,
                "top_pitchers": dom
            })

        if status == "Final":
            feed = fetch(f"{BASE}/v1.1/game/{g['gamePk']}/feed/live")
            lines = feed["liveData"]["linescore"]
            box = feed["liveData"]["boxscore"]

            hitters = []
            pitchers = []

            for side in ["away", "home"]:
                for bid in box["teams"][side]["batters"]:
                    b = box["teams"][side]["players"][f"ID{bid}"]["stats"]["batting"]
                    if n(b.get("hits")) >= 2 or n(b.get("homeRuns")) >= 1:
                        hitters.append(
                            box["teams"][side]["players"][f"ID{bid}"]["person"]["fullName"]
                        )

                for pid in box["teams"][side]["pitchers"][:1]:
                    p = box["teams"][side]["players"][f"ID{pid}"]["stats"]["pitching"]
                    if n(p.get("strikeOuts")) >= 6:
                        pitchers.append(
                            box["teams"][side]["players"][f"ID{pid}"]["person"]["fullName"]
                        )

            postgame.append({
                "game": f"{away['name']} @ {home['name']}",
                "final_score": f"{lines['teams']['away']['runs']}–{lines['teams']['home']['runs']}",
                "hitters": hitters,
                "pitchers": pitchers
            })

# =====================================================
# REAL AI DAILY RECAP (SAFE)
# =====================================================

def ai_daily_recap(postgame_games):
    if not client or not postgame_games:
        return None

    games_text = "\n".join([
        f"{g['game']} — Final Score: {g['final_score']}. "
        f"Key hitters: {', '.join(g['hitters']) if g['hitters'] else 'multiple contributors'}. "
        f"Key pitchers: {', '.join(g['pitchers']) if g['pitchers'] else 'staff effort'}."
        for g in postgame_games
    ])

    prompt = f"""
You are a professional baseball writer for ESPN and The Athletic.

Write a daily MLB recap with:
- A strong headline
- One paragraph per game
- Mention key moments, standout hitters, and pitching
- An engaging but factual tone
- End with a short "What it means" section

Games:
{games_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )

    return {
        "headline": f"MLB Daily Recap — {NOW.strftime('%B %d, %Y')}",
        "article": response.choices[0].message.content.strip()
    }

ai_recap = ai_daily_recap(postgame)

# =====================================================
# WRITE FILES
# =====================================================

json.dump({"updated_at": NOW.isoformat(), "games": daily}, open("daily.json","w"), indent=2)
json.dump({"updated_at": NOW.isoformat(), "games": live}, open("live.json","w"), indent=2)
json.dump({"updated_at": NOW.isoformat(), "games": postgame}, open("postgame.json","w"), indent=2)

if ai_recap:
    json.dump(ai_recap, open("daily_recap.json","w"), indent=2)
