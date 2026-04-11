# imports
# config

# ----------------
# Utilities
# ----------------
def fetch(...)
def n(...)

# ----------------
# Pitcher helpers
# ----------------
def pitcher_hand(...)
def pitcher_era(...)
def pitcher_last5(...)
...

# ----------------
# Hitter helpers
# ----------------
def hitter_season(...)
def hitter_split_season(...)
def last10_ab(...)
...

# ----------------
# Build daily / live / postgame
# ----------------
daily = []
live = []
postgame = []

# (your existing loops)

# ----------------
# ✅ AI Recap (NEW)
# ----------------
def ai_daily_recap(postgame_games):
    ...

ai_recap = ai_daily_recap(postgame)

# ----------------
# Write files
# ----------------
json.dump(daily.json)
json.dump(live.json)
json.dump(postgame.json)
json.dump(daily_recap.json)
