print("### RUN_ENGINE MAIN BRANCH EXECUTING ###")
print("### GROQ ENGINE VERSION RUNNING ###")

import json
import os
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from groq import Groq

BASE = "https://statsapi.mlb.com/api"
MLB_TZ = ZoneInfo("America/New_York")
NOW = datetime.now(MLB_TZ)

TODAY = NOW.date().isoformat()
YESTERDAY = (NOW - timedelta(days=1)).date().isoformat()
SEASON = NOW.year

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
FETCH_CACHE = {}


def fetch(url):
    if url in FETCH_CACHE:
        return FETCH_CACHE[url]

    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
        FETCH_CACHE[url] = payload
        return payload


def safe_number(value, default=0):
    return value if value is not None else default


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_ip(ip_value):
    text = str(ip_value or "0")
    if "." not in text:
        return safe_float(text, 0.0)

    whole, frac = text.split(".", 1)
    outs_lookup = {"0": 0, "1": 1, "2": 2}
    outs = outs_lookup.get(frac, 0)
    return safe_float(whole, 0.0) + (outs / 3.0)


def is_finished_game(status_block):
    abstract = str(status_block.get("abstractGameState", "")).strip().lower()
    detailed = str(status_block.get("detailedState", "")).strip().lower()
    coded = str(status_block.get("codedGameState", "")).strip().upper()

    return (
        abstract == "final"
        or detailed in {"final", "game over", "completed early"}
        or coded == "F"
    )


def format_baseball_avg(value):
    if value is None:
        return "N/A"
    text = f"{value:.3f}"
    return text[1:] if text.startswith("0") else text


def get_player_stat_block(team, player_id, stat_group):
    player = team.get("players", {}).get(f"ID{player_id}", {})
    return player.get("stats", {}).get(stat_group, {})


def get_player_name(team, player_id):
    player = team.get("players", {}).get(f"ID{player_id}", {})
    return player.get("person", {}).get("fullName", "Unknown Player")


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def player_profile(player_id):
    people = fetch(f"{BASE}/v1/people/{player_id}").get("people", [])
    return people[0] if people else {}


def player_stat_group(player_id, group, stats_type="season", extra_query=""):
    url = (
        f"{BASE}/v1/people/{player_id}/stats"
        f"?stats={stats_type}&group={group}&season={SEASON}"
    )
    if extra_query:
        url += f"&{extra_query}"

    stats = fetch(url).get("stats", [])
    splits = stats[0].get("splits", []) if stats else []
    return splits


def team_active_hitters(team_id):
    roster = fetch(
        f"{BASE}/v1/teams/{team_id}/roster?rosterType=active"
    ).get("roster", [])

    hitters = []
    for entry in roster:
        person = entry.get("person", {})
        position = entry.get("position", {}).get("abbreviation")
        if position == "P":
            continue
        hitters.append({"id": person.get("id"), "name": person.get("fullName")})

    return hitters


def pitcher_last_three(player_id):
    splits = player_stat_group(player_id, "pitching", "gameLog")
    starts = []

    for split in reversed(splits):
        stat = split.get("stat", {})
        if safe_number(stat.get("gamesStarted")) >= 1:
            starts.append(stat)
        if len(starts) == 3:
            break

    if not starts:
        return {
            "starts_used": 0,
            "avg_ip": "N/A",
            "avg_k": "N/A",
            "avg_bb": "N/A",
            "avg_era": "N/A",
            "whip": "N/A",
            "quality_starts": 0,
            "wins": 0,
            "last_start": {
                "ip": "N/A",
                "k": "N/A",
                "bb": "N/A",
                "er": "N/A",
                "hits": "N/A",
                "decision": "N/A",
            },
        }

    total_ip = sum(parse_ip(start.get("inningsPitched")) for start in starts)
    total_k = sum(safe_number(start.get("strikeOuts")) for start in starts)
    total_bb = sum(safe_number(start.get("baseOnBalls")) for start in starts)
    total_er = sum(safe_number(start.get("earnedRuns")) for start in starts)
    total_hits = sum(safe_number(start.get("hits")) for start in starts)

    quality_starts = 0
    wins = 0

    for start in starts:
        ip = parse_ip(start.get("inningsPitched"))
        er = safe_number(start.get("earnedRuns"))
        if ip >= 6 and er <= 3:
            quality_starts += 1
        if str(start.get("decision", "")).lower() == "win":
            wins += 1

    starts_count = len(starts)
    whip = ((total_hits + total_bb) / total_ip) if total_ip else None
    era = ((total_er * 9) / total_ip) if total_ip else None
    last_start = starts[0]

    return {
        "starts_used": starts_count,
        "avg_ip": f"{(total_ip / starts_count):.1f}",
        "avg_k": f"{(total_k / starts_count):.1f}",
        "avg_bb": f"{(total_bb / starts_count):.1f}",
        "avg_era": f"{era:.2f}" if era is not None else "N/A",
        "whip": f"{whip:.2f}" if whip is not None else "N/A",
        "quality_starts": quality_starts,
        "wins": wins,
        "last_start": {
            "ip": last_start.get("inningsPitched", "N/A"),
            "k": safe_number(last_start.get("strikeOuts")),
            "bb": safe_number(last_start.get("baseOnBalls")),
            "er": safe_number(last_start.get("earnedRuns")),
            "hits": safe_number(last_start.get("hits")),
            "decision": last_start.get("decision", "N/A"),
        },
    }


def hitter_split(player_id, sit_code):
    try:
        splits = player_stat_group(
            player_id,
            "hitting",
            "statSplits",
            extra_query=f"sitCodes={sit_code}",
        )
        if not splits:
            return {"avg": "N/A", "hits": 0}

        stat = splits[0].get("stat", {})
        return {
            "avg": stat.get("avg", "N/A"),
            "hits": safe_number(stat.get("hits")),
        }
    except Exception:
        return {"avg": "N/A", "hits": 0}


def hitter_overview(player_id):
    profile = player_profile(player_id)
    season_splits = player_stat_group(player_id, "hitting", "season")
    season = season_splits[0].get("stat", {}) if season_splits else {}
    game_logs = player_stat_group(player_id, "hitting", "gameLog")

    recent_games = list(reversed(game_logs))[:5]
    hit_streak = 0
    for split in recent_games:
        if safe_number(split.get("stat", {}).get("hits")) > 0:
            hit_streak += 1
        else:
            break

    last_ten = list(reversed(game_logs))[:10]
    last10_hits = sum(safe_number(item.get("stat", {}).get("hits")) for item in last_ten)
    last10_ab = sum(safe_number(item.get("stat", {}).get("atBats")) for item in last_ten)
    last10_pa = sum(safe_number(item.get("stat", {}).get("plateAppearances")) for item in last_ten)
    last10_avg = (last10_hits / last10_ab) if last10_ab else None

    recent_avg = last10_hits / last10_ab if last10_ab else None
    hot = recent_avg is not None and recent_avg >= 0.350 and hit_streak >= 2
    cold = recent_avg is not None and recent_avg <= 0.180 and last10_pa >= 8

    return {
        "name": profile.get("fullName", "Unknown Hitter"),
        "hand": profile.get("batSide", {}).get("code", "N/A"),
        "streak": hit_streak,
        "hot": hot,
        "cold": cold,
        "stats": {
            "avg": season.get("avg", "N/A"),
            "obp": season.get("obp", "N/A"),
            "slg": season.get("slg", "N/A"),
            "ops": season.get("ops", "N/A"),
            "pa": safe_number(season.get("plateAppearances")),
        },
        "last10": {
            "label": "Last 10 games",
            "avg": format_baseball_avg(last10_avg) if last10_avg is not None else "N/A",
            "hits": last10_hits,
            "ab": last10_ab,
            "pa": last10_pa,
        },
        "vsRHP": hitter_split(player_id, "vr"),
        "vsLHP": hitter_split(player_id, "vl"),
        "risp": {"avg": hitter_split(player_id, "risp").get("avg", "N/A")},
    }


def team_hitter_summaries(team_id):
    hitters = []

    for player in team_active_hitters(team_id):
        player_id = player.get("id")
        if not player_id:
            continue

        try:
            hitters.append(hitter_overview(player_id))
        except Exception:
            continue

    hitters.sort(key=lambda item: safe_number(item.get("stats", {}).get("pa")), reverse=True)
    return hitters[:6]


def pitcher_summary(pitcher):
    if not pitcher:
        return {}

    out = {
        "id": pitcher.get("id"),
        "name": pitcher.get("fullName", "Unknown Pitcher"),
        "hand": "N/A",
        "era": "N/A",
        "last3": {
            "starts_used": 0,
            "avg_ip": "N/A",
            "avg_k": "N/A",
            "avg_bb": "N/A",
            "avg_era": "N/A",
            "whip": "N/A",
            "quality_starts": 0,
            "wins": 0,
            "last_start": {
                "ip": "N/A",
                "k": "N/A",
                "bb": "N/A",
                "er": "N/A",
                "hits": "N/A",
                "decision": "N/A",
            },
        },
    }

    pitcher_id = pitcher.get("id")
    if not pitcher_id:
        return out

    try:
        profile = player_profile(pitcher_id)
        out["hand"] = profile.get("pitchHand", {}).get("code", "N/A")
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

    try:
        out["last3"] = pitcher_last_three(pitcher_id)
    except Exception as exc:
        out["last3_error"] = str(exc)

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


def build_recap_stat_lines(boxscore):
    hitter_lines = []
    pitcher_lines = []

    for side in ["away", "home"]:
        team = boxscore.get("teams", {}).get(side, {})

        for batter_id in team.get("batters", []):
            batting = get_player_stat_block(team, batter_id, "batting")
            hits = safe_number(batting.get("hits"))
            home_runs = safe_number(batting.get("homeRuns"))
            rbi = safe_number(batting.get("rbi"))
            if hits >= 2 or home_runs >= 1 or rbi >= 2:
                hitter_lines.append(
                    f"{get_player_name(team, batter_id)}: {hits} H, {home_runs} HR, {rbi} RBI"
                )

        for pitcher_id in team.get("pitchers", []):
            pitching = get_player_stat_block(team, pitcher_id, "pitching")
            strikeouts = safe_number(pitching.get("strikeOuts"))
            innings = pitching.get("inningsPitched", "0.0")
            earned_runs = safe_number(pitching.get("earnedRuns"))
            if strikeouts >= 5:
                pitcher_lines.append(
                    f"{get_player_name(team, pitcher_id)}: {innings} IP, {strikeouts} K, {earned_runs} ER"
                )

    return hitter_lines[:6], pitcher_lines[:6]


def season_leaders():
    try:
        payload = fetch(
            f"{BASE}/v1/stats?stats=season&group=hitting,pitching&playerPool=qualified&sportIds=1&season={SEASON}"
        )
        splits = payload.get("stats", [])

        hitting = []
        pitching = []

        for stat_group in splits:
            group_name = stat_group.get("group", {}).get("displayName", "")
            for split in stat_group.get("splits", []):
                player_name = split.get("player", {}).get("fullName", "Unknown")
                stat = split.get("stat", {})
                if group_name == "hitting":
                    hitting.append({"name": player_name, "stat": stat})
                elif group_name == "pitching":
                    pitching.append({"name": player_name, "stat": stat})

        avg_ops = sorted(hitting, key=lambda x: safe_float(x["stat"].get("avg", 0)), reverse=True)[:5]
        power = sorted(hitting, key=lambda x: safe_number(x["stat"].get("homeRuns", 0)), reverse=True)[:5]
        strikeouts = sorted(pitching, key=lambda x: safe_number(x["stat"].get("strikeOuts", 0)), reverse=True)[:5]
        prevention = sorted(pitching, key=lambda x: safe_float(x["stat"].get("era", 999)),)[:5]

        return {
            "avg_ops": [
                f"{item['name']}: AVG {item['stat'].get('avg', 'N/A')} | OPS {item['stat'].get('ops', 'N/A')}"
                for item in avg_ops
            ],
            "power": [
                f"{item['name']}: HR {item['stat'].get('homeRuns', 0)} | RBI {item['stat'].get('rbi', 0)}"
                for item in power
            ],
            "pitching": [
                f"{item['name']}: K {item['stat'].get('strikeOuts', 0)} | W {item['stat'].get('wins', 0)}"
                for item in strikeouts
            ],
            "run_prevention": [
                f"{item['name']}: ERA {item['stat'].get('era', 'N/A')} | WHIP {item['stat'].get('whip', 'N/A')}"
                for item in prevention
            ],
        }
    except Exception:
        return {
            "avg_ops": [],
            "power": [],
            "pitching": [],
            "run_prevention": [],
        }


def build_finished_games_today(postgame_today):
    finished = []

    for game in postgame_today:
        top_pitch = game["pitcher_lines"][0] if game["pitcher_lines"] else "No top pitching line available"
        top_hit = game["hitter_lines"][0] if game["hitter_lines"] else "No top batting line available"

        stat_parts = [f"{game['winner']} beat {game['loser']} {game['final_score']}."]
        if top_pitch != "No top pitching line available":
            stat_parts.append(f"Top pitching: {top_pitch}.")
        if top_hit != "No top batting line available":
            stat_parts.append(f"Top batting: {top_hit}.")

        finished.append({
            "game": game["game"],
            "final_score": game["final_score"],
            "winner": game["winner"],
            "loser": game["loser"],
            "top_pitching_line": top_pitch,
            "top_batting_line": top_hit,
            "stat_summary": " ".join(stat_parts),
        })

    return finished


def build_previous_day_recap(yesterday_postgame):
    recap = {
        "all_games": [],
        "season_leaders": season_leaders(),
    }

    if not yesterday_postgame:
        return recap

    if client:
        try:
            raw_games = "\n".join(
                [
                    (
                        f"Game: {game['game']}\n"
                        f"Final: {game['final_score']}\n"
                        f"Winner: {game['winner']}\n"
                        f"Loser: {game['loser']}\n"
                        f"Exact hitter lines: {'; '.join(game['hitter_lines']) if game['hitter_lines'] else 'No standout hitter line provided'}\n"
                        f"Exact pitcher lines: {'; '.join(game['pitcher_lines']) if game['pitcher_lines'] else 'No standout pitcher line provided'}\n"
                    )
                    for game in yesterday_postgame
                ]
            )

            prompt = f"""
You are writing concise MLB game recaps for a modern baseball dashboard.

Return valid JSON only with this exact schema:
{{
  "all_games": [
    {{
      "game": "...",
      "final_score": "...",
      "top_pitching_line": "...",
      "top_batting_line": "...",
      "summary": "2-3 sentence natural recap",
      "impact_player": "..."
    }}
  ]
}}

Rules:
- Use only the exact stats and names provided below.
- Do not invent numbers, innings, strikeouts, hits, home runs, RBI, or events.
- Write naturally, like a professional MLB recap writer.
- Mention the players who most shaped the game.
- If pitching was the biggest factor, make that clear.
- If offense was decisive, make that clear.
- If a home run or major RBI performance is listed, use it directly when relevant.
- Keep each game summary to 2-3 sentences.
- Avoid robotic or repetitive phrasing.
- Output JSON only.

Games:
{raw_games}
"""

            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

            content = response.choices[0].message.content.strip()
            parsed = json.loads(content)
            parsed["season_leaders"] = recap["season_leaders"]
            return parsed
        except Exception:
            pass

    for game in yesterday_postgame:
        top_pitch = game["pitcher_lines"][0] if game["pitcher_lines"] else "No top pitching line available"
        top_hit = game["hitter_lines"][0] if game["hitter_lines"] else "No top batting line available"

        summary_parts = [f"{game['winner']} beat {game['loser']} {game['final_score']}."]
        if top_pitch != "No top pitching line available":
            summary_parts.append(f"{top_pitch} was the leading pitching performance in the game.")
        if top_hit != "No top batting line available":
            summary_parts.append(f"{top_hit} was the key offensive contribution.")

        summary = " ".join(summary_parts)
        impact = top_hit if ("HR" in top_hit or "RBI" in top_hit) else top_pitch

        recap["all_games"].append({
            "game": game["game"],
            "final_score": game["final_score"],
            "top_pitching_line": top_pitch,
            "top_batting_line": top_hit,
            "summary": summary,
            "impact_player": impact,
        })

    return recap


schedule_today = fetch(
    f"{BASE}/v1/schedule?sportId=1&date={TODAY}&hydrate=probablePitcher"
)

daily = []
live = []
postgame_today = []
errors = []

for date_block in schedule_today.get("dates", []):
    for game in date_block.get("games", []):
        try:
            away = game["teams"]["away"]["team"]["name"]
            home = game["teams"]["home"]["team"]["name"]
            away_team_id = game["teams"]["away"]["team"]["id"]
            home_team_id = game["teams"]["home"]["team"]["id"]
            venue = game["venue"]["name"]
            start = game["gameDate"]
            status = game["status"]["abstractGameState"]

            away_pitcher = game["teams"]["away"].get("probablePitcher")
            home_pitcher = game["teams"]["home"].get("probablePitcher")

            daily.append({
                "gamePk": game.get("gamePk"),
                "away_team": away,
                "home_team": home,
                "venue": venue,
                "start": start,
                "status": status,
                "away_pitcher": pitcher_summary(away_pitcher),
                "home_pitcher": pitcher_summary(home_pitcher),
                "away_hitters": team_hitter_summaries(away_team_id),
                "home_hitters": team_hitter_summaries(home_team_id),
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
                hitter_lines, pitcher_lines = build_recap_stat_lines(box)

                postgame_today.append({
                    "gamePk": game.get("gamePk"),
                    "game": f"{away} @ {home}",
                    "winner": winner,
                    "loser": loser,
                    "final_score": f"{away_runs}-{home_runs}",
                    "hitters": hitters,
                    "pitchers": pitchers,
                    "hitter_lines": hitter_lines,
                    "pitcher_lines": pitcher_lines,
                })
        except Exception as exc:
            errors.append({
                "gamePk": game.get("gamePk"),
                "stage": "today_schedule_loop",
                "error": str(exc),
            })

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
            hitter_lines, pitcher_lines = build_recap_stat_lines(box)

            yesterday_postgame.append({
                "gamePk": game.get("gamePk"),
                "game": f"{away} @ {home}",
                "winner": winner,
                "loser": loser,
                "final_score": f"{away_runs}-{home_runs}",
                "hitters": hitters,
                "pitchers": pitchers,
                "hitter_lines": hitter_lines,
                "pitcher_lines": pitcher_lines,
            })
        except Exception as exc:
            errors.append({
                "gamePk": game.get("gamePk"),
                "stage": "yesterday_schedule_loop",
                "error": str(exc),
            })

finished_games_today = build_finished_games_today(postgame_today)
previous_day_recap = build_previous_day_recap(yesterday_postgame)

timestamp = NOW.isoformat()

write_json("daily.json", {"updated_at": timestamp, "games": daily, "errors": errors})
write_json("live.json", {"updated_at": timestamp, "games": live, "errors": errors})
write_json("postgame.json", {"updated_at": timestamp, "games": finished_games_today, "errors": errors})
write_json("yesterday_postgame.json", {"updated_at": timestamp, "games": yesterday_postgame, "errors": errors})
write_json(
    "yesterday_recap.json",
    {
        "date": YESTERDAY,
        "headline": f"MLB Daily Recap - {datetime.fromisoformat(YESTERDAY).strftime('%B %d, %Y')}",
        "dashboard_recap": previous_day_recap,
    },
)

print(f"Wrote daily.json with {len(daily)} games")
print(f"Wrote live.json with {len(live)} games")
print(f"Wrote postgame.json with {len(finished_games_today)} games")
print(f"Wrote yesterday_postgame.json with {len(yesterday_postgame)} games")
print("Wrote yesterday_recap.json")
