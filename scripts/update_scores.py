#!/usr/bin/env python3
"""
Pulls every FBS game involving a Big Ten team for a given week from ESPN's
public (unofficial) scoreboard endpoint, and upserts the results into the
Supabase `games` table.

Env vars required (set as GitHub Actions secrets):
  SUPABASE_URL          e.g. https://xxxxx.supabase.co
  SUPABASE_SERVICE_KEY  the service_role key (NOT the anon key — this needs
                         write access and must never be shipped to the browser)

Usage:
  python update_scores.py --week 3
  python update_scores.py --week 3 --year 2026
"""

import argparse
import os
import sys
import requests

BIG_TEN_TEAMS = {
    "Illinois", "Indiana", "Iowa", "Maryland", "Michigan", "Michigan State",
    "Minnesota", "Nebraska", "Northwestern", "Ohio State", "Oregon",
    "Penn State", "Purdue", "Rutgers", "UCLA", "USC", "Washington", "Wisconsin",
}

# ESPN's own display names sometimes differ slightly from the ones used
# elsewhere in this app. Map anything that doesn't already match
# BIG_TEN_TEAMS / opponent_classification exactly.
NAME_FIXES = {
    "Southern California": "USC",
    "Miami (OH)": "Miami (OH)",
}


def normalize(name: str) -> str:
    return NAME_FIXES.get(name, name)


def fetch_week(week: int, year: int) -> list[dict]:
    """
    groups=12 is ESPN's internal id for the Big Ten; scoped this way the
    scoreboard endpoint returns every game involving a Big Ten team, including
    their non-conference matchups (not just Big-Ten-vs-Big-Ten games).
    """
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
    params = {"groups": 12, "week": week, "year": year, "seasontype": 2, "limit": 100}
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json().get("events", [])


def parse_event(event: dict, week: int) -> dict | None:
    try:
        competition = event["competitions"][0]
        competitors = competition["competitors"]
        home = next(c for c in competitors if c["homeAway"] == "home")
        away = next(c for c in competitors if c["homeAway"] == "away")

        home_name = normalize(home["team"]["location"] if home["team"].get("location") else home["team"]["displayName"])
        away_name = normalize(away["team"]["location"] if away["team"].get("location") else away["team"]["displayName"])

        # only keep games that actually involve a Big Ten team
        if home_name not in BIG_TEN_TEAMS and away_name not in BIG_TEN_TEAMS:
            return None

        status = competition.get("status", {}).get("type", {}).get("state")  # "pre" | "in" | "post"
        home_score = int(home["score"]) if status != "pre" and home.get("score") not in (None, "") else None
        away_score = int(away["score"]) if status != "pre" and away.get("score") not in (None, "") else None

        winner = None
        if status == "post" and home_score is not None and away_score is not None and home_score != away_score:
            winner = home_name if home_score > away_score else away_name

        return {
            "week": week,
            "home": home_name,
            "away": away_name,
            "kickoff_at": event["date"],  # ISO8601, UTC
            "home_score": home_score,
            "away_score": away_score,
            "winner": winner,
        }
    except (KeyError, StopIteration, ValueError) as e:
        print(f"  ! skipping malformed event: {e}", file=sys.stderr)
        return None


def upsert_games(rows: list[dict], base_url: str, service_key: str) -> None:
    if not rows:
        print("  no rows to upsert")
        return
    resp = requests.post(
        f"{base_url}/rest/v1/games?on_conflict=week,away,home",
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",  # upsert on the unique (week,away,home) constraint
        },
        json=rows,
        timeout=20,
    )
    if not resp.ok:
        print(f"  ! Supabase upsert failed: {resp.status_code} {resp.text}", file=sys.stderr)
        resp.raise_for_status()
    print(f"  upserted {len(rows)} game(s) for week {rows[0]['week']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()

    base_url = os.environ["SUPABASE_URL"].rstrip("/")
    service_key = os.environ["SUPABASE_SERVICE_KEY"]

    print(f"Fetching week {args.week}, {args.year}...")
    events = fetch_week(args.week, args.year)
    rows = [r for r in (parse_event(e, args.week) for e in events) if r is not None]

    print(f"  found {len(rows)} Big Ten-involved game(s)")
    upsert_games(rows, base_url, service_key)


if __name__ == "__main__":
    main()
