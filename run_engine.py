print("### RUN_ENGINE MAIN BRANCH EXECUTING ###")
print("### GROQ ENGINE VERSION RUNNING ###")

import json
import os
import re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

try:
    from groq import Groq
except ImportError:
    Groq = None

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
client = Groq(api_key=GROQ_API_KEY) if (Groq and GROQ_API_KEY) else None

errors = []


# =====================================================
# UTILITIES
# =====================================================

def fetch(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8")


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def normalize_whitespace(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def safe_number(value, default=0):
    return value if value is not None else default


def is_finished_game(status_block):
    abstract = str(status_block.get("abstractGameState", "")).strip().lower()
    detailed = str(status_block.get("detailedState", "")).strip().lower()
    coded = str(status_block.get("codedGameState", "")).strip().upper()

    return (
        abstract == "final"
        or detailed in {"final", "game over", "completed early"}
        or coded == "F"
    )


def get_player_stat_block(team, player_id, stat_group):
    player = team.get("players", {}).get(f"ID{player_id}", {})
    return player.get("stats", {}).get(stat_group, {})


def get_player_name(team, player_id):
    player = team.get("players", {}).get(f"ID{player_id}", {})
    return player.get("person", {}).get("fullName", "Unknown Player")


# =====================================================
# NEWS / TRANSACTIONS HELPERS
# =====================================================

def parse_news_rss(url, limit=8):
    items = []

    try:
        root = ET.fromstring(fetch_text(url))
        for item in root.findall(".//item")[:limit]:
            items.append(
                {
                    "title": normalize_whitespace(item.findtext("title", "")),
                    "link": normalize_whitespace(item.findtext("link", "")),
                    "published": normalize_whitespace(item.findtext("pubDate", "")),
                    "summary": normalize_whitespace(item.findtext("description", "")),
                }
            )
    except Exception as exc:
        errors.append({
            "stage": "news_rss",
            "error": str(exc),
        })

    return [item for item in items if item.get("title")]


def get_transaction_text(transaction):
    description = normalize_whitespace(
        transaction.get("description")
        or transaction.get("typeDesc")
        or transaction.get("note")
        or ""
    )
    type_desc = normalize_whitespace(transaction.get("typeDesc", ""))
    return " | ".join(part for part in [description, type_desc] if part)


def get_transaction_team_name(transaction):
    for key in ["team", "toTeam", "fromTeam"]:
        team = transaction.get(key)
        if isinstance(team, dict) and team.get("name"):
            return team["name"]

    for key in ["teamName", "toTeamName", "fromTeamName"]:
        if transaction.get(key):
            return normalize_whitespace(transaction.get(key))

    return "MLB"


def is_trade_transaction(text):
    lowered = normalize_whitespace(text).lower()
    return "trade" in lowered or "traded" in lowered


def is_il_add_transaction(text):
    lowered = normalize_whitespace(text).lower()
    il_markers = ["injured list", "7-day il", "10-day il", "15-day il", "60-day il"]
    add_markers = ["placed", "transferred", "returned to il", "returned to the injured list"]
    return any(marker in lowered for marker in il_markers) and any(
        marker in lowered for marker in add_markers
    )


def is_il_remove_transaction(text):
    lowered = normalize_whitespace(text).lower()
    remove_markers = [
        "reinstated from the injured list",
        "reinstated from 7-day il",
        "reinstated from 10-day il",
        "reinstated from 15-day il",
        "reinstated from 60-day il",
        "activated from the injured list",
        "returned from the injured list",
    ]
    return any(marker in lowered for marker in remove_markers)


def extract_il_type(text):
    lowered = normalize_whitespace(text).lower()
    match = re.search(r"(\d+)-day il", lowered)
    if match:
        return f"{match.group(1)}-day IL"
    if "injured list" in lowered:
        return "Injured List"
    return "IL"


def extract_injury_note(text):
    normalized = normalize_whitespace(text)
    if " with " in normalized:
        return normalized.split(" with ", 1)[1].rstrip(".")
    if " due to " in normalized:
        return normalized.split(" due to ", 1)[1].rstrip(".")
    return normalized


def build_recent_transaction_feed(days=10):
    start_date = (NOW - timedelta(days=days)).date().isoformat()
    transaction_feed = []

    try:
        payload = fetch(
            f"{BASE}/v1/transactions?sportId=1&startDate={start_date}&endDate={TODAY}"
        )
        transactions = sorted(
            payload.get("transactions", []),
            key=lambda item: (item.get("date", ""), item.get("id", 0)),
            reverse=True,
        )

        for transaction in transactions:
            person = transaction.get("person") or {}
            text = get_transaction_text(transaction)

            if not text:
                continue

            transaction_feed.append(
                {
                    "date": transaction.get("date", ""),
                    "player": person.get("fullName", "Unknown Player"),
                    "team": get_transaction_team_name(transaction),
                    "text": text,
                }
            )
    except Exception as exc:
        errors.append({
            "stage": "recent_transactions",
            "error": str(exc),
        })

    return transaction_feed


def build_injury_updates(transactions, limit=12):
    updates = []

    for transaction in transactions:
        text = transaction["text"]
        if is_il_add_transaction(text) or is_il_remove_transaction(text):
            updates.append(
                {
                    "date": transaction["date"],
                    "team": transaction["team"],
                    "player": transaction["player"],
                    "update": text,
                }
            )
        if len(updates) >= limit:
            break

    return updates


def build_trade_updates(transactions, limit=10):
    updates = []

    for transaction in transactions:
        if is_trade_transaction(transaction["text"]):
            updates.append(
                {
                    "date": transaction["date"],
                    "team": transaction["team"],
                    "player": transaction["player"],
                    "update": transaction["text"],
                }
            )
        if len(updates) >= limit:
            break

    return updates


def build_team_injured_lists():
    teams_payload = fetch(f"{BASE}/v1/teams?sportId=1&season={SEASON}")
    teams = sorted(
        [team for team in teams_payload.get("teams", []) if team.get("active", True)],
        key=lambda item: item.get("name", ""),
    )
    season_start = f"{SEASON}-01-01"
    team_injuries = []

    for team in teams:
        team_id = team.get("id")
        team_name = team.get("name", "Unknown Team")
        active_il = {}

        if not team_id:
            continue

        try:
            transactions_payload = fetch(
                f"{BASE}/v1/transactions"
                f"?teamId={team_id}&sportId=1&startDate={season_start}&endDate={TODAY}"
            )
            transactions = sorted(
                transactions_payload.get("transactions", []),
                key=lambda item: (item.get("date", ""), item.get("id", 0)),
            )

            for transaction in transactions:
                person = transaction.get("person") or {}
                player_id = person.get("id")
                player_name = person.get("fullName", "Unknown Player")
                combined = get_transaction_text(transaction)

                if not player_id or not combined:
                    continue

                if is_il_add_transaction(combined):
                    active_il[player_id] = {
                        "player_id": player_id,
                        "name": player_name,
                        "il_type": extract_il_type(combined),
                        "date": transaction.get("date", ""),
                        "note": extract_injury_note(combined),
                        "description": combined,
                    }
                elif is_il_remove_transaction(combined):
                    active_il.pop(player_id, None)

            players = sorted(active_il.values(), key=lambda item: item["name"])
            team_injuries.append(
                {
                    "team_id": team_id,
                    "team_name": team_name,
                    "injured_count": len(players),
                    "players": players,
                }
            )
        except Exception as exc:
            errors.append({
                "teamId": team_id,
                "stage": "injury_transactions",
                "error": str(exc),
            })
            team_injuries.append(
                {
                    "team_id": team_id,
                    "team_name": team_name,
                    "injured_count": 0,
                    "players": [],
                    "error": str(exc),
                }
            )

    return team_injuries


def build_news_roundup(top_news, injury_updates, trade_updates):
    roundup = {
        "updated_at": NOW.isoformat(),
        "headline": "MLB News Desk",
        "article": "No news roundup generated yet.",
        "top_news": top_news,
        "injury_updates": injury_updates,
        "trade_updates": trade_updates,
    }

    if client:
        try:
            news_lines = "\n".join([f"- {item['title']}" for item in top_news[:6]]) or "- No major top headlines available."
            injury_lines = "\n".join([f"- {item['team']}: {item['player']} ({item['update']})" for item in injury_updates[:8]]) or "- No recent injury updates available."
            trade_lines = "\n".join([f"- {item['team']}: {item['player']} ({item['update']})" for item in trade_updates[:8]]) or "- No recent MLB trade updates available."

            prompt = f"""
You are an MLB recap writer for a dashboard.

Write a concise previous-day MLB recap.

Requirements:
- Start with a strong headline on the first line
- Then write 3 to 4 sentences total with creative sports journalism and make each story different
- Focus on the biggest offensive impact players and pitching impact players across the completed games
- Mention standout hitters, home run power, RBI impact, dominant pitchers, strikeout performances, and run prevention
- Keep it sharp, factual, and easy to read on mobile
- No bullet points
- No section headers
- No speculation
- If there were only a few games, still keep it to 3 to 4 sentences and center the most important performances

Games:
{games_text}
"""

Top news:
{news_lines}

Injuries:
{injury_lines}

Trades / roster movement:
{trade_lines}
"""

            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )

            content = response.choices[0].message.content.strip()
            parts = content.split("\n", 1)
            roundup["headline"] = parts[0].strip() if parts else "MLB News Desk"
            roundup["article"] = parts[1].strip() if len(parts) > 1 else content
        except Exception as exc:
            roundup["article"] = f"Groq news roundup error: {str(exc)}"
    else:
        roundup["article"] = (
            "Top MLB headlines, injury movement, and trade updates are available below. "
            "Add a GROQ_API_KEY to generate the AI-written daily roundup."
        )

    return roundup

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fetch_stat_leaders(stat_group, stat_type, limit=5):
    try:
        payload = fetch(
            f"{BASE}/v1/stats/leaders"
            f"?leaderCategories={stat_type}"
            f"&statGroup={stat_group}"
            f"&season={SEASON}"
            f"&sportId=1"
            f"&limit={limit}"
        )
        return payload.get("leagueLeaders", [])
    except Exception as exc:
        errors.append({
            "stage": f"leaders_{stat_group}_{stat_type}",
            "error": str(exc),
        })
        return []


def extract_leader_entries(league_leaders):
    if not league_leaders:
        return []
    leaders = league_leaders[0].get("leaders", [])
    return leaders if isinstance(leaders, list) else []


def build_season_leaders():
    avg_leaders = extract_leader_entries(fetch_stat_leaders("hitting", "battingAverage", 5))
    ops_leaders = extract_leader_entries(fetch_stat_leaders("hitting", "ops", 5))
    hr_leaders = extract_leader_entries(fetch_stat_leaders("hitting", "homeRuns", 5))
    rbi_leaders = extract_leader_entries(fetch_stat_leaders("hitting", "runsBattedIn", 5))
    so_leaders = extract_leader_entries(fetch_stat_leaders("pitching", "strikeouts", 5))
    win_leaders = extract_leader_entries(fetch_stat_leaders("pitching", "wins", 5))
    era_leaders = extract_leader_entries(fetch_stat_leaders("pitching", "earnedRunAverage", 5))
    whip_leaders = extract_leader_entries(fetch_stat_leaders("pitching", "whip", 5))

    return {
        "avg_ops": [
            f"{entry['person']['fullName']} ({entry['team']['name']}) - AVG {entry['value']}"
            for entry in avg_leaders
        ] + [
            f"{entry['person']['fullName']} ({entry['team']['name']}) - OPS {entry['value']}"
            for entry in ops_leaders
        ],
        "power": [
            f"{entry['person']['fullName']} ({entry['team']['name']}) - HR {entry['value']}"
            for entry in hr_leaders
        ] + [
            f"{entry['person']['fullName']} ({entry['team']['name']}) - RBI {entry['value']}"
            for entry in rbi_leaders
        ],
        "pitching": [
            f"{entry['person']['fullName']} ({entry['team']['name']}) - K {entry['value']}"
            for entry in so_leaders
        ] + [
            f"{entry['person']['fullName']} ({entry['team']['name']}) - W {entry['value']}"
            for entry in win_leaders
        ],
        "run_prevention": [
            f"{entry['person']['fullName']} ({entry['team']['name']}) - ERA {entry['value']}"
            for entry in era_leaders
        ] + [
            f"{entry['person']['fullName']} ({entry['team']['name']}) - WHIP {entry['value']}"
            for entry in whip_leaders
        ],
    }
# =====================================================
# PLAYER STAT HELPERS
# =====================================================

def format_hitter_stats(stat):
    if not stat:
        return {}

    return {
        "avg": stat.get("avg", "N/A"),
        "obp": stat.get("obp", "N/A"),
        "slg": stat.get("slg", "N/A"),
        "ops": stat.get("ops", "N/A"),
        "homeRuns": stat.get("homeRuns", 0),
        "rbi": stat.get("rbi", 0),
    }


def build_team_hitters(team_id):
    hitters = []

    try:
        roster_payload = fetch(f"{BASE}/v1/teams/{team_id}/roster?rosterType=active")
        roster = roster_payload.get("roster", [])

        for player in roster:
            person = player.get("person", {})
            position_type = (
                player.get("position", {}).get("type", "")
                or player.get("position", {}).get("abbreviation", "")
            )

            if str(position_type).lower() == "pitcher":
                continue

            player_id = person.get("id")
            player_name = person.get("fullName", "Unknown Player")

            if not player_id:
                continue

            try:
                stats_payload = fetch(
                    f"{BASE}/v1/people/{player_id}/stats"
                    f"?stats=season&group=hitting&season={SEASON}"
                )
                stats = stats_payload.get("stats", [])
                splits = stats[0].get("splits", []) if stats else []
                stat_block = splits[0].get("stat", {}) if splits else {}

                hitters.append({
                    "name": player_name,
                    "stats": format_hitter_stats(stat_block),
                })
            except Exception as exc:
                errors.append({
                    "playerId": player_id,
                    "stage": "hitter_stats",
                    "error": str(exc),
                })

        hitters.sort(
            key=lambda item: (
                -float(item["stats"].get("ops", 0) or 0) if str(item["stats"].get("ops", "0")).replace(".", "", 1).isdigit() else 0,
                item["name"]
            )
        )

        return hitters[:9]

    except Exception as exc:
        errors.append({
            "teamId": team_id,
            "stage": "build_team_hitters",
            "error": str(exc),
        })
        return []


def pitcher_summary(pitcher):
    if not pitcher:
        return {}

    out = {
        "id": pitcher.get("id"),
        "name": pitcher.get("fullName", "Unknown Pitcher"),
        "hand": "N/A",
        "era": "N/A",
    }

    pitcher_id = pitcher.get("id")
    if not pitcher_id:
        return out

    try:
        people = fetch(f"{BASE}/v1/people/{pitcher_id}").get("people", [])
        if people:
            out["hand"] = people[0].get("pitchHand", {}).get("code", "N/A")
    except Exception as exc:
        out["profile_error"] = str(exc)

    try:
        stats = fetch(
            f"{BASE}/v1/people/{pitcher_id}/stats"
            f"?stats=season&group=pitching&season={SEASON}"
        ).get("stats", [])
        splits = stats[0].get("splits", []) if stats else []
        if splits:
            out["era"] = splits[0].get("stat", {}).get("era", "N/A")
    except Exception as exc:
        out["stats_error"] = str(exc)

    return out


def build_live_or_final_highlights(boxscore, pick_final_pitcher=False):
    hitters = []
    pitchers = []

    for side in ["away", "home"]:
        team = boxscore.get("teams", {}).get(side, {})

        for batter_id in team.get("batters", []):
            batting = get_player_stat_block(team, batter_id, "batting")
            if safe_number(batting.get("hits")) >= 2 or safe_number(batting.get("homeRuns")) >= 1:
                hitters.append(get_player_name(team, batter_id))

        pitcher_ids = team.get("pitchers", [])
        selected_ids = pitcher_ids[:1] if pick_final_pitcher else pitcher_ids[-1:]

        for pitcher_id in selected_ids:
            pitching = get_player_stat_block(team, pitcher_id, "pitching")
            if safe_number(pitching.get("strikeOuts")) >= 6:
                pitchers.append(get_player_name(team, pitcher_id))

    return hitters, pitchers


# =====================================================
# BUILD TODAY
# =====================================================

schedule_today = fetch(
    f"{BASE}/v1/schedule?sportId=1&date={TODAY}&hydrate=probablePitcher"
)

daily = []
live = []
postgame_today = []

for date_block in schedule_today.get("dates", []):
    for game in date_block.get("games", []):
        try:
            away = game["teams"]["away"]["team"]["name"]
            home = game["teams"]["home"]["team"]["name"]
            venue = game["venue"]["name"]
            start = game["gameDate"]
            status = game["status"]["abstractGameState"]

            away_pitcher = game["teams"]["away"].get("probablePitcher")
            home_pitcher = game["teams"]["home"].get("probablePitcher")

            away_team_id = game["teams"]["away"]["team"]["id"]
            home_team_id = game["teams"]["home"]["team"]["id"]

            daily.append({
                "gamePk": game.get("gamePk"),
                "away_team": away,
                "home_team": home,
                "venue": venue,
                "start": start,
                "status": status,
                "away_pitcher": pitcher_summary(away_pitcher),
                "home_pitcher": pitcher_summary(home_pitcher),
                "away_hitters": build_team_hitters(away_team_id),
                "home_hitters": build_team_hitters(home_team_id),
            })


            if status in ["Live", "In Progress"]:
                feed = fetch(f"{BASE}/v1.1/game/{game['gamePk']}/feed/live")
                lines = feed.get("liveData", {}).get("linescore", {})
                box = feed.get("liveData", {}).get("boxscore", {})
                hot_hitters, top_pitchers = build_live_or_final_highlights(box, pick_final_pitcher=False)

                live.append({
                    "gamePk": game.get("gamePk"),
                    "game": f"{away} @ {home}",
                    "score": f"{lines.get('teams', {}).get('away', {}).get('runs', 0)}-{lines.get('teams', {}).get('home', {}).get('runs', 0)}",
                    "inning": lines.get("currentInningOrdinal"),
                    "hot_hitters": hot_hitters,
                    "top_pitchers": top_pitchers,
                })

            if is_finished_game(game.get("status", {})):
                feed = fetch(f"{BASE}/v1.1/game/{game['gamePk']}/feed/live")
                lines = feed.get("liveData", {}).get("linescore", {})
                box = feed.get("liveData", {}).get("boxscore", {})

                away_runs = lines.get("teams", {}).get("away", {}).get("runs", 0)
                home_runs = lines.get("teams", {}).get("home", {}).get("runs", 0)
                winner = away if away_runs > home_runs else home
                loser = home if away_runs > home_runs else away
                hitters, pitchers = build_live_or_final_highlights(box, pick_final_pitcher=True)

                postgame_today.append({
                    "gamePk": game.get("gamePk"),
                    "game": f"{away} @ {home}",
                    "winner": winner,
                    "loser": loser,
                    "final_score": f"{away_runs}-{home_runs}",
                    "hitters": hitters,
                    "pitchers": pitchers,
                })
        except Exception as exc:
            errors.append({
                "gamePk": game.get("gamePk"),
                "stage": "today_schedule_loop",
                "error": str(exc),
            })


# =====================================================
# BUILD YESTERDAY
# =====================================================

schedule_yesterday = fetch(
    f"{BASE}/v1/schedule?sportId=1&date={YESTERDAY}"
)

yesterday_postgame = []

for date_block in schedule_yesterday.get("dates", []):
    for game in date_block.get("games", []):
        if not is_finished_game(game.get("status", {})):
            continue

        try:
            away = game["teams"]["away"]["team"]["name"]
            home = game["teams"]["home"]["team"]["name"]

            feed = fetch(f"{BASE}/v1.1/game/{game['gamePk']}/feed/live")
            lines = feed.get("liveData", {}).get("linescore", {})
            box = feed.get("liveData", {}).get("boxscore", {})

            away_runs = lines.get("teams", {}).get("away", {}).get("runs", 0)
            home_runs = lines.get("teams", {}).get("home", {}).get("runs", 0)
            winner = away if away_runs > home_runs else home
            loser = home if away_runs > home_runs else away
            hitters, pitchers = build_live_or_final_highlights(box, pick_final_pitcher=True)

            yesterday_postgame.append({
                "gamePk": game.get("gamePk"),
                "game": f"{away} @ {home}",
                "winner": winner,
                "loser": loser,
                "final_score": f"{away_runs}-{home_runs}",
                "hitters": hitters,
                "pitchers": pitchers,
            })
        except Exception as exc:
            errors.append({
                "gamePk": game.get("gamePk"),
                "stage": "yesterday_schedule_loop",
                "error": str(exc),
            })


# =====================================================
# YESTERDAY AI RECAP
# =====================================================
yesterday_recap = {
    "updated_at": NOW.isoformat(),
    "date": YESTERDAY,
    "dashboard_recap": {
        "headline": f"MLB Daily Recap - {datetime.fromisoformat(YESTERDAY).strftime('%B %d, %Y')}",
        "article": "No recap generated yet.",
        "all_games": [],
        "season_leaders": {
            "avg_ops": [],
            "power": [],
            "pitching": [],
            "run_prevention": []
        }
    }
}

if yesterday_postgame and client:
    try:
        games_text = "\n".join(
            [
                (
                    f"Game: {game['game']}\n"
                    f"Final: {game['final_score']}\n"
                    f"Winner: {game['winner']}\n"
                    f"Loser: {game['loser']}\n"
                    f"Impact Hitters: {', '.join(game['hitters']) if game['hitters'] else 'Multiple contributors'}\n"
                    f"Impact Pitchers: {', '.join(game['pitchers']) if game['pitchers'] else 'Staff effort'}\n"
                )
                for game in yesterday_postgame
            ]
        )

        prompt = f"""
You are an MLB recap writer for a dashboard.

Write a concise previous-day MLB recap.

Requirements:
- Start with a strong headline on the first line
- Then write 3 to 4 sentences total
- Focus on the biggest offensive impact players and pitching impact players across the completed games
- Mention standout hitters, home run power, RBI impact, dominant pitchers, strikeout performances, and run prevention
- Keep it sharp, factual, and easy to read on mobile
- No bullet points
- No section headers
- No speculation
- If there were only a few games, still keep it to 3 to 4 sentences and center the most important performances

Games:
{games_text}
"""

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
        )

        yesterday_recap["dashboard_recap"]["article"] = response.choices[0].message.content.strip()
    except Exception as exc:
        yesterday_recap["dashboard_recap"]["article"] = f"Groq error: {str(exc)}"
elif yesterday_postgame and not client:
    yesterday_recap["dashboard_recap"]["article"] = "Groq recap skipped because GROQ_API_KEY is not set."
else:
    yesterday_recap["dashboard_recap"]["article"] = "No final games were available for yesterday."

yesterday_recap["dashboard_recap"]["all_games"] = [
    {
        "game": game["game"],
        "final_score": game["final_score"],
        "top_pitching_line": ", ".join(game.get("pitchers", [])) if game.get("pitchers") else "No standout pitching line available.",
        "top_batting_line": ", ".join(game.get("hitters", [])) if game.get("hitters") else "No standout batting line available.",
        "summary": f"{game['winner']} beat {game['loser']} {game['final_score']}.",
        "impact_player": (game.get("hitters") or game.get("pitchers") or ["N/A"])[0]
    }
    for game in yesterday_postgame
]

yesterday_recap["dashboard_recap"]["season_leaders"] = build_season_leaders()
# =====================================================
# NEWS / IL FILES
# =====================================================

top_news = parse_news_rss("https://www.mlb.com/feeds/news/rss.xml", limit=8)
recent_transactions = build_recent_transaction_feed(days=10)
injury_updates = build_injury_updates(recent_transactions, limit=12)
trade_updates = build_trade_updates(recent_transactions, limit=10)

mlb_news = build_news_roundup(top_news, injury_updates, trade_updates)

injury_report = {
    "updated_at": NOW.isoformat(),
    "teams": build_team_injured_lists(),
    "errors": errors,
}


# =====================================================
# WRITE FILES
# =====================================================

timestamp = NOW.isoformat()

write_json("daily.json", {"updated_at": timestamp, "games": daily, "errors": errors})
write_json("live.json", {"updated_at": timestamp, "games": live, "errors": errors})
write_json("postgame.json", {"updated_at": timestamp, "games": postgame_today, "errors": errors})
write_json("yesterday_postgame.json", {"updated_at": timestamp, "games": yesterday_postgame, "errors": errors})
write_json("yesterday_recap.json", yesterday_recap)
write_json("mlb_news.json", mlb_news)
write_json("injury_report.json", injury_report)

print(f"Wrote daily.json with {len(daily)} games")
print(f"Wrote live.json with {len(live)} games")
print(f"Wrote postgame.json with {len(postgame_today)} games")
print(f"Wrote yesterday_postgame.json with {len(yesterday_postgame)} games")
print("Wrote yesterday_recap.json")
print(f"Wrote mlb_news.json with {len(top_news)} headlines")
print(f"Wrote injury_report.json with {len(injury_report['teams'])} teams")

