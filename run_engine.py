print("### RUN_ENGINE MAIN BRANCH EXECUTING ###")
print("### GROQ ENGINE VERSION RUNNING ###")

import json
import os
from datetime import datetime, timedelta
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from groq import Groq

# =====================================================
# CONFIG
# =====================================================

BASE = "https://statsapi.mlb.com/api"
MLB_TZ = ZoneInfo("America/New_York")
NOW = datetime.now(MLB_TZ)

TODAY = NOW.date().isoformat()
YESTERDAY = (NOW - timedelta(days=1)).date().isoformat()
SEASON = NOW.year

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# =====================================================
# UTILITIES
# =====================================================

def fetch(url):
    with urlopen(url) as r:
        return json.loads(r.read().decode("utf-8"))

def safe(x):
    return x if x is not None else 0

# =====================================================
# PLAYER STAT HELPERS (SEASON‑TO‑DATE)
# =====================================================

def pitcher_summary(p):
    if not p:
        return {}

    out = {
        "name": p["fullName"],
        "hand": "N/A",
        "era": "N/A"
    }

    try:
        profile = fetch(f"{BASE}/v1/people/{p['id']}")["people"][0]
        out["hand"] = profile["pitchHand"]["code"]
    except:
        pass

    try:
        s = fetch(
            f"{BASE}/v1/people/{p['id']}/stats"
            f"?stats=season&group=pitching&season={SEASON}"
        )["stats"][0]["splits"][0]["stat"]
        out["era"] = s.get("era", "N/A")
    except:
        pass

    return out

# =====================================================
# BUILD TODAY (PRE‑GAME / LIVE / FINAL)
# =====================================================

schedule_today = fetch(
    f"{BASE}/v1/schedule?sportId=1&date={TODAY}&hydrate=probablePitcher"
)

daily = []
live = []
postgame_today = []

for d in schedule_today.get("dates", []):
    for g in d.get("games", []):

        away = g["teams"]["away"]["team"]["name"]
        home = g["teams"]["home"]["team"]["name"]
        venue = g["venue"]["name"]
        start = g["gameDate"]
        status = g["status"]["abstractGameState"]

        ap = g["teams"]["away"].get("probablePitcher")
        hp = g["teams"]["home"].get("probablePitcher")

        # ---------- DAILY (PRE‑GAME CONTEXT) ----------
        daily.append({
            "away_team": away,
            "home_team": home,
            "venue": venue,
            "start": start,
            "away_pitcher": pitcher_summary(ap),
            "home_pitcher": pitcher_summary(hp)
        })

        # ---------- LIVE ----------
        if status in ["Live", "In Progress"]:
            feed = fetch(f"{BASE}/v1.1/game/{g['gamePk']}/feed/live")
            lines = feed["liveData"]["linescore"]
            box = feed["liveData"]["boxscore"]

            hot = []
            dom = []

            for side in ["away", "home"]:
                team = box["teams"][side]
                for bid in team["batters"]:
                    b = team["players"][f"ID{bid}"]["stats"]["batting"]
                    if safe(b.get("hits")) >= 2:
                        hot.append(
                            team["players"][f"ID{bid}"]["person"]["fullName"]
                        )

                for pid in team["pitchers"][-1:]:
                    p = team["players"][f"ID{pid}"]["stats"]["pitching"]
                    if safe(p.get("strikeOuts")) >= 6:
                        dom.append(
                            team["players"][f"ID{pid}"]["person"]["fullName"]
                        )

            live.append({
                "game": f"{away} @ {home}",
                "score": f"{lines['teams']['away']['runs']}–{lines['teams']['home']['runs']}",
                "inning": lines.get("currentInningOrdinal"),
                "hot_hitters": hot,
                "top_pitchers": dom
            })

        # ---------- FINAL (TODAY) ----------
        if status == "Final":
            feed = fetch(f"{BASE}/v1.1/game/{g['gamePk']}/feed/live")
            lines = feed["liveData"]["linescore"]
            box = feed["liveData"]["boxscore"]

            away_runs = lines["teams"]["away"]["runs"]
            home_runs = lines["teams"]["home"]["runs"]

            winner = away if away_runs > home_runs else home
            loser = home if away_runs > home_runs else away

            hitters = []
            pitchers = []

            for side in ["away", "home"]:
                team = box["teams"][side]
                for bid in team["batters"]:
                    b = team["players"][f"ID{bid}"]["stats"]["batting"]
                    if safe(b.get("hits")) >= 2 or safe(b.get("homeRuns")) >= 1:
                        hitters.append(
                            team["players"][f"ID{bid}"]["person"]["fullName"]
                        )

                for pid in team["pitchers"][:1]:
                    p = team["players"][f"ID{pid}"]["stats"]["pitching"]
                    if safe(p.get("strikeOuts")) >= 6:
                        pitchers.append(
                            team["players"][f"ID{pid}"]["person"]["fullName"]
                        )

            postgame_today.append({
                "game": f"{away} @ {home}",
                "winner": winner,
                "loser": loser,
                "final_score": f"{away_runs}–{home_runs}",
                "hitters": hitters,
                "pitchers": pitchers
            })

# =====================================================
# BUILD YESTERDAY (FINAL + AI RECAP)
# =====================================================

schedule_yesterday = fetch(
    f"{BASE}/v1/schedule?sportId=1&date={YESTERDAY}"
)

yesterday_postgame = []

for d in schedule_yesterday.get("dates", []):
    for g in d.get("games", []):
        if g["status"]["abstractGameState"] != "Final":
            continue

        away = g["teams"]["away"]["team"]["name"]
        home = g["teams"]["home"]["team"]["name"]

        feed = fetch(f"{BASE}/v1.1/game/{g['gamePk']}/feed/live")
        lines = feed["liveData"]["linescore"]
        box = feed["liveData"]["boxscore"]

        away_runs = lines["teams"]["away"]["runs"]
        home_runs = lines["teams"]["home"]["runs"]

        winner = away if away_runs > home_runs else home
        loser = home if away_runs > home_runs else away

        hitters = []
        pitchers = []

        for side in ["away", "home"]:
            team = box["teams"][side]
            for bid in team["batters"]:
                b = team["players"][f"ID{bid}"]["stats"]["batting"]
                if safe(b.get("hits")) >= 2 or safe(b.get("homeRuns")) >= 1:
                    hitters.append(
                        team["players"][f"ID{bid}"]["person"]["fullName"]
                    )

            for pid in team["pitchers"][:1]:
                p = team["players"][f"ID{pid}"]["stats"]["pitching"]
                if safe(p.get("strikeOuts")) >= 6:
                    pitchers.append(
                        team["players"][f"ID{pid}"]["person"]["fullName"]
                    )

        yesterday_postgame.append({
            "game": f"{away} @ {home}",
            "winner": winner,
            "loser": loser,
            "final_score": f"{away_runs}–{home_runs}",
            "hitters": hitters,
            "pitchers": pitchers
        })

# =====================================================
# YESTERDAY AI RECAP (GROQ)
# =====================================================

yesterday_recap = None

if yesterday_postgame and client:
    games_text = "\n".join([
        f"""
Game: {g['game']}
Final: {g['final_score']}
Winner: {g['winner']}
Loser: {g['loser']}
Hitters: {', '.join(g['hitters']) if g['hitters'] else 'Multiple contributors'}
Pitchers: {', '.join(g['pitchers']) if g['pitchers'] else 'Staff effort'}
"""
        for g in yesterday_postgame
    ])

    prompt = f"""
You are a professional MLB columnist.

Write a YESTERDAY MLB recap with:
- A strong headline
- One paragraph per game
- Specific stats and reasons
- End with a section titled "Biggest Story of the Day"

Avoid generic language.

Games:
{games_text}
"""

    response = client.chat.completions.create(
    model="llama3-8b-8192",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.6
)

    yesterday_recap = {
        "date": YESTERDAY,
        "headline": f"MLB Daily Recap — {datetime.fromisoformat(YESTERDAY).strftime('%B %d, %Y')}",
        "article": response.choices[0].message.content.strip()
    }

# =====================================================
# WRITE FILES (FORCE OVERWRITE)
# =====================================================

json.dump({"updated_at": NOW.isoformat(), "games": daily}, open("daily.json", "w"), indent=2)
json.dump({"updated_at": NOW.isoformat(), "games": live}, open("live.json", "w"), indent=2)
json.dump({"updated_at": NOW.isoformat(), "games": postgame_today}, open("postgame.json", "w"), indent=2)

if yesterday_recap:
    json.dump(yesterday_recap, open("yesterday_recap.json", "w"), indent=2)
