#!/usr/bin/env python3
import json, re
from pathlib import Path
from datetime import datetime, timezone
import requests

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
URL = re.search(r"const SUPABASE_URL='([^']+)'", HTML).group(1)
KEY = re.search(r"const SUPABASE_ANON_KEY='([^']+)'", HTML).group(1)
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

def get(path, params=None):
    r = requests.get(URL + "/rest/v1/" + path, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def rpc(name, payload):
    r = requests.post(URL + "/rest/v1/rpc/" + name, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

games = get("games", {"select":"*", "order":"week.asc,kickoff_at.asc"})
classifications = get("opponent_classification", {"select":"*", "order":"opponent.asc"})
players = get("players_public", {"select":"*", "order":"name.asc"})
board = rpc("get_public_board", {})
board = sorted(board, key=lambda r: (r.get("week") or 0, (r.get("player_name") or "").lower()))

weeks = sorted({int(g["week"]) for g in games})
deadlines = {str(w): rpc("week_deadline", {"p_week":w}) for w in weeks}
reopen_times = {str(w): rpc("week_reopen_time", {"p_week":w}) for w in weeks}

pick_by_player_week = {(r["player_id"], int(r["week"])): r.get("team") for r in board}
game_by_week_team = {}
for g in games:
    w = int(g["week"])
    game_by_week_team[(w, g["home"])] = g
    game_by_week_team[(w, g["away"])] = g

active = {p["id"] for p in players}
eliminated_week = {}
pool_end_week = None
winner_id = None

for w in weeks:
    entrants = list(active)
    pending = False
    losers = []
    deadline = deadlines.get(str(w))
    deadline_dt = datetime.fromisoformat(deadline.replace("Z","+00:00")) if deadline else None
    now = datetime.now(timezone.utc)
    for pid in entrants:
        team = pick_by_player_week.get((pid, w))
        if not team:
            if deadline_dt and now >= deadline_dt:
                losers.append(pid)
            else:
                pending = True
            continue
        g = game_by_week_team.get((w, team))
        winner = g.get("winner") if g else None
        if not winner:
            pending = True
        elif winner != team:
            losers.append(pid)
    for pid in losers:
        if pid in active:
            active.remove(pid)
            eliminated_week.setdefault(pid, w)
    if pending:
        break
    if len(active) <= 1:
        pool_end_week = w
        winner_id = next(iter(active)) if len(active) == 1 else None
        break

player_state = []
for p in players:
    player_state.append({
        "id": p["id"],
        "name": p["name"],
        "fan_of": p.get("fan_of"),
        "created_at": p.get("created_at"),
        "alive": p["id"] in active,
        "eliminated_week": eliminated_week.get(p["id"])
    })

winner_name = next((p["name"] for p in players if p["id"] == winner_id), None)

out = {
    "meta": {
        "season": 2026,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": "Supabase public read interfaces",
        "contains_private_auth_data": False,
        "pool_end_week": pool_end_week,
        "winner_id": winner_id,
        "winner_name": winner_name,
        "survivors": len(active),
        "weeks": weeks
    },
    "games": games,
    "opponent_classification": classifications,
    "players": players,
    "board": board,
    "week_deadlines": deadlines,
    "week_reopen_times": reopen_times,
    "final_player_state": player_state
}

dest = ROOT / "archive" / "2026-season.json"
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(json.dumps(out, indent=2, sort_keys=False) + "\n", encoding="utf-8")
print(f"Wrote {dest}")
print(json.dumps(out["meta"], indent=2))
