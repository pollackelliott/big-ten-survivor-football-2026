#!/usr/bin/env python3
"""
Pulls every FBS game involving a Big Ten team for a given week from ESPN's
public (unofficial) scoreboard endpoint, validates the response against the
schedule already loaded in Supabase, and upserts safe score/result updates.

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

# ESPN display/API names that are known to differ from this app's canonical
# names. Keep this list intentionally small: anything else is surfaced as a
# workflow failure so a new mismatch cannot remain silent.
NAME_FIXES = {
    "Southern California": "USC",
    "Massachusetts": "UMass",
    "San José State": "San Jose State",
}


def normalize(name: str) -> str:
    return NAME_FIXES.get(name, name)


def supabase_headers(service_key: str) -> dict[str, str]:
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }


def fetch_known_opponents(base_url: str, service_key: str) -> set[str]:
    """Return the canonical opponent names configured in Supabase."""
    resp = requests.get(
        f"{base_url}/rest/v1/opponent_classification?select=opponent",
        headers=supabase_headers(service_key),
        timeout=20,
    )
    if not resp.ok:
        print(
            f"  ! Supabase opponent lookup failed: {resp.status_code} {resp.text}",
            file=sys.stderr,
        )
        resp.raise_for_status()

    rows = resp.json()
    return {row["opponent"] for row in rows if row.get("opponent")}


def fetch_expected_game_keys(
    base_url: str, service_key: str, week: int
) -> set[tuple[str, str]]:
    """Return (away, home) pairs already loaded for this pool week."""
    resp = requests.get(
        f"{base_url}/rest/v1/games?select=away,home&week=eq.{week}",
        headers=supabase_headers(service_key),
        timeout=20,
    )
    if not resp.ok:
        print(
            f"  ! Supabase schedule lookup failed: {resp.status_code} {resp.text}",
            file=sys.stderr,
        )
        resp.raise_for_status()

    return {
        (row["away"], row["home"])
        for row in resp.json()
        if row.get("away") and row.get("home")
    }


def fetch_week(week: int, year: int) -> list[dict]:
    """
    groups=5 is ESPN's internal id for the Big Ten; scoped this way the
    scoreboard endpoint returns every game involving a Big Ten team, including
    their non-conference matchups (not just Big-Ten-vs-Big-Ten games).
    """
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
    params = {
        "groups": 5,
        "week": week,
        "year": year,
        "seasontype": 2,
        "limit": 100,
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json().get("events", [])


def parse_event(event: dict, week: int) -> dict:
    competition = event["competitions"][0]
    competitors = competition["competitors"]
    home = next(c for c in competitors if c["homeAway"] == "home")
    away = next(c for c in competitors if c["homeAway"] == "away")

    home_name = normalize(
        home["team"]["location"]
        if home["team"].get("location")
        else home["team"]["displayName"]
    )
    away_name = normalize(
        away["team"]["location"]
        if away["team"].get("location")
        else away["team"]["displayName"]
    )

    # groups=5 should return only Big Ten-involved games. If ESPN ever changes
    # a Big Ten display name (or the endpoint behavior changes), fail visibly
    # rather than silently dropping the event.
    if home_name not in BIG_TEN_TEAMS and away_name not in BIG_TEN_TEAMS:
        raise ValueError(
            f"ESPN group=5 event has no recognized Big Ten team: {away_name} @ {home_name}"
        )

    status = competition.get("status", {}).get("type", {}).get("state")
    home_score = (
        int(home["score"])
        if status != "pre" and home.get("score") not in (None, "")
        else None
    )
    away_score = (
        int(away["score"])
        if status != "pre" and away.get("score") not in (None, "")
        else None
    )

    winner = None
    if (
        status == "post"
        and home_score is not None
        and away_score is not None
        and home_score != away_score
    ):
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


def game_key(row: dict) -> tuple[str, str]:
    return row["away"], row["home"]


def find_unknown_names(rows: list[dict], known_opponents: set[str]) -> list[str]:
    known_names = BIG_TEN_TEAMS | known_opponents
    return sorted(
        {
            team
            for row in rows
            for team in (row["home"], row["away"])
            if team not in known_names
        }
    )


def upsert_games(rows: list[dict], base_url: str, service_key: str) -> None:
    if not rows:
        print("  no safe rows to upsert")
        return
    resp = requests.post(
        f"{base_url}/rest/v1/games?on_conflict=week,away,home",
        headers={
            **supabase_headers(service_key),
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        },
        json=rows,
        timeout=20,
    )
    if not resp.ok:
        print(
            f"  ! Supabase upsert failed: {resp.status_code} {resp.text}",
            file=sys.stderr,
        )
        resp.raise_for_status()
    print(f"  upserted {len(rows)} game(s) for week {rows[0]['week']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()

    base_url = os.environ["SUPABASE_URL"].rstrip("/")
    service_key = os.environ["SUPABASE_SERVICE_KEY"]

    print(f"Fetching week {args.week}, {args.year}...")
    known_opponents = fetch_known_opponents(base_url, service_key)
    expected_keys = fetch_expected_game_keys(base_url, service_key, args.week)
    print(f"  loaded {len(known_opponents)} configured opponent name(s) from Supabase")
    print(f"  loaded {len(expected_keys)} existing week-{args.week} game(s) from Supabase")

    events = fetch_week(args.week, args.year)
    rows: list[dict] = []
    parse_errors: list[str] = []

    for event in events:
        try:
            rows.append(parse_event(event, args.week))
        except (KeyError, StopIteration, TypeError, ValueError) as exc:
            event_id = event.get("id", "unknown")
            message = f"event {event_id}: {exc}"
            parse_errors.append(message)
            print(f"::error title=ESPN event parse failure::{message}", file=sys.stderr)

    print(f"  found {len(rows)} recognized Big Ten-involved ESPN game(s)")

    unknown_names = find_unknown_names(rows, known_opponents)
    for name in unknown_names:
        print(
            f"::error title=Unrecognized ESPN team name::"
            f"{name!r} is not a Big Ten team or opponent_classification name. "
            f"Add a deliberate NAME_FIXES alias or correct the database seed.",
            file=sys.stderr,
        )

    espn_keys = {game_key(row) for row in rows}
    missing_expected: set[tuple[str, str]] = set()
    unexpected_espn: set[tuple[str, str]] = set()

    if expected_keys:
        missing_expected = expected_keys - espn_keys
        unexpected_espn = espn_keys - expected_keys

        for away, home in sorted(missing_expected):
            print(
                f"::error title=Scheduled game missing from ESPN::"
                f"Week {args.week}: {away} @ {home} exists in Supabase but was not returned by ESPN.",
                file=sys.stderr,
            )

        for away, home in sorted(unexpected_espn):
            print(
                f"::error title=Unexpected ESPN matchup::"
                f"Week {args.week}: ESPN returned {away} @ {home}, but that matchup is not in the loaded Supabase schedule. "
                "It was not upserted automatically; review for a schedule or naming change.",
                file=sys.stderr,
            )

        # Once a schedule exists, only update rows that match it exactly. This
        # prevents a changed/renamed matchup from creating a duplicate game row
        # that could make opponent lookup ambiguous. Valid matching games still
        # receive their score updates even when another matchup needs review.
        safe_rows = [row for row in rows if game_key(row) in expected_keys]
    else:
        # Preseason/bootstrap behavior: if the week has never been loaded, ESPN
        # is allowed to establish the initial schedule.
        safe_rows = rows

    upsert_games(safe_rows, base_url, service_key)

    problems = (
        len(parse_errors)
        + len(unknown_names)
        + len(missing_expected)
        + len(unexpected_espn)
    )
    if problems:
        raise RuntimeError(
            f"score ingestion completed with {problems} validation problem(s); "
            "valid matching rows were preserved and the annotated errors above require review"
        )

    print("  validation passed; ESPN response matches the configured schedule")


if __name__ == "__main__":
    main()
