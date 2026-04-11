import json
import os
from datetime import datetime
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

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# =====================================================
# UTILITIES
# =====================================================

def fetch(url):
    with urlopen(url) as r:
        return json.loads(r.read().decode("utf-8"))

# =====================================================
# BUILD DAILY / LIVE / POSTGAME
# =====================================================

schedule = fetch(
    f"{BASE}/v1/schedule?sportId=1&date={TODAY}"
)

daily = []
live = []
postgame = []

for d in schedule.get("dates", []):
    for g in d.get("games", []):

        away = g["teams"]["away"]["team"]["name"]
        home = g["teams"]["home"]["team"]["name"]
        status = g["status"]["abstractGameState"]

        daily.append({
            "away_team": away,
            "home_team": home,
            "start": g["gameDate"]
        })

        if status in ["Live", "In Progress"]:
            feed = fetch(f"{BASE}/v1.1/game/{g['gamePk']}/feed/live")
            lines = feed["liveData"]["linescore"]

            live.append({
                "game": f"{away} @ {home}",
                "score": f"{lines['teams']['away']['runs']}–{lines['teams']['home']['runs']}",
                "inning": lines.get("currentInningOrdinal")
            })

        if status == "Final":
            feed = fetch(f"{BASE}/v1.1/game/{g['gamePk']}/feed/live")
            lines = feed["liveData"]["linescore"]

            away_runs = lines["teams"]["away"]["runs"]
            home_runs = lines["teams"]["home"]["runs"]

            winner = away if away_runs > home_runs else home
            loser = home if away_runs > home_runs else away

            postgame.append({
                "game": f"{away} @ {home}",
                "winner": winner,
                "loser": loser,
                "final_score": f"{away_runs}–{home_runs}"
            })

# =====================================================
# DAILY RECAP (GROQ)
# =====================================================

recap = None

if postgame and client:
    try:
        games_text = "\n".join(
            f"{g['winner']} defeated {g['loser']} ({g['final_score']})"
            for g in postgame
        )

        prompt = f"""
You are a professional MLB beat writer.

Write a daily MLB recap with:
- A strong headline
- One paragraph per game
- Clear winners and reasons
- A short 'What It Means' section

Games:
{games_text}
"""

        response = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6
        )

        recap = {
            "date": TODAY,
            "headline": f"MLB Daily Recap — {NOW.strftime('%B %d, %Y')}",
            "article": response.choices[0].message.content.strip()
        }

    except Exception as e:
        recap = {
            "date": TODAY,
            "headline": f"MLB Daily Recap — {NOW.strftime('%B %d, %Y')}",
            "article": f"Groq error: {str(e)}"
        }

if not recap and postgame:
    recap = {
        "date": TODAY,
        "headline": f"MLB Daily Recap — {NOW.strftime('%B %d, %Y')}",
        "article": "One or more MLB games have gone final today. Recap generation will retry automatically."
    }

# =====================================================
# WRITE FILES
# =====================================================

if recap:
    with open("daily_recap.json", "w") as f:
        json.dump(recap, f, indent=2)

json.dump({"updated_at": NOW.isoformat(), "games": daily}, open("daily.json", "w"), indent=2)
json.dump({"updated_at": NOW.isoformat(), "games": live}, open("live.json", "w"), indent=2)
json.dump({"updated_at": NOW.isoformat(), "games": postgame}, open("postgame.json", "w"), indent=2)
