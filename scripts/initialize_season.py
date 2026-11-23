#!/usr/bin/env python3
"""
Initialize a new football survivor season from the commissioner's color-coded
P4G5 Excel workbook.

The workbook is the schedule authority:
  - sheet name: P4G5
  - column A: conference teams
  - row 1, columns B:N: Weeks 1-13
  - cell text: opponent, optionally prefixed by "at " or "vs. "
  - yellow fill (#FFD966): power-conference nonconference opponent
  - blue fill   (#4A86E8): G5 opponent
  - gray fill   (#CCCCCC): FCS / ineligible opponent
  - no fill: conference game

ESPN is used only to resolve canonical home/away and exact kickoff timestamps.

Required environment variables when writing to Supabase:
  SUPABASE_URL
  SUPABASE_ANON_KEY       (public client key; written to app-config.js)
  SUPABASE_SERVICE_KEY    (secret; NEVER written to the repository)
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
import requests

ROOT = Path(__file__).resolve().parents[1]
CONFERENCE = "Big Ten"
ESPN_GROUP_ID = 5
SHEET_NAME = "P4G5"
WEEKS = 13
CHICAGO = ZoneInfo("America/Chicago")

CONFERENCE_TEAMS = {
    "Illinois",
    "Indiana",
    "Iowa",
    "Maryland",
    "Michigan",
    "Michigan State",
    "Minnesota",
    "Nebraska",
    "Northwestern",
    "Ohio State",
    "Oregon",
    "Penn State",
    "Purdue",
    "Rutgers",
    "UCLA",
    "USC",
    "Washington",
    "Wisconsin",
}

NAME_FIXES = {
    # ESPN/API aliases
    "Southern California": "USC",
    "Massachusetts": "UMass",

    # Common commissioner-grid shorthand
    "Mich. State": "Michigan State",
    "Michigan St.": "Michigan State",
    "Penn St.": "Penn State",
    "Ohio St.": "Ohio State",
}

# Workbook fill -> (eligible, database category)
FILL_CLASSES = {
    "FFD966": (True, "not_g5"),   # yellow: other power conference / Notre Dame
    "4A86E8": (True, "g5"),       # blue: G5
    "CCCCCC": (False, None),      # gray: FCS / ineligible
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def normalize_name(name: str) -> str:
    clean = " ".join(str(name).strip().split())
    canonical = {team.lower(): team for team in CONFERENCE_TEAMS}
    fixes = {alias.lower(): target for alias, target in NAME_FIXES.items()}
    return fixes.get(clean.lower(), canonical.get(clean.lower(), clean))


def normalized_fill(cell) -> str | None:
    if cell.fill.fill_type != "solid":
        return None
    color = cell.fill.fgColor
    rgb = color.rgb
    if rgb:
        return str(rgb)[-6:].upper()
    # The canonical workbook uses literal RGB fills. Theme/indexed fills are
    # rejected so a changed workbook style cannot silently change rule meaning.
    return None


def parse_opponent(raw) -> tuple[str, str | None]:
    value = " ".join(str(raw).strip().split())
    lower = value.lower()
    if lower.startswith("at "):
        return normalize_name(value[3:]), "away"
    if lower.startswith("vs. "):
        return normalize_name(value[4:]), "vs"
    if lower.startswith("vs "):
        return normalize_name(value[3:]), "vs"
    return normalize_name(value), None


def locate_schedule_file(requested: str | None) -> Path:
    if requested:
        path = (ROOT / requested).resolve() if not Path(requested).is_absolute() else Path(requested)
        if not path.exists():
            fail(f"Schedule workbook not found: {path}")
        return path

    data_dir = ROOT / "data"
    candidates = sorted(
        p for p in data_dir.glob("*.xlsx")
        if not p.name.startswith("~$")
    )
    if len(candidates) != 1:
        fail(
            "Expected exactly one .xlsx schedule workbook in data/. "
            f"Found {len(candidates)}: {[p.name for p in candidates]}"
        )
    return candidates[0]


def infer_year(path: Path, explicit_year: int | None) -> int:
    if explicit_year:
        return explicit_year
    match = re.search(r"(20\d{2})", path.name)
    if match:
        return int(match.group(1))
    year = datetime.now(CHICAGO).year
    print(f"::warning::No year found in workbook filename; using current year {year}.")
    return year


def parse_workbook(path: Path) -> tuple[list[dict], list[dict]]:
    wb = load_workbook(path, data_only=False, read_only=False)
    if SHEET_NAME not in wb.sheetnames:
        fail(f"Workbook must contain a sheet named {SHEET_NAME!r}. Found: {wb.sheetnames}")
    ws = wb[SHEET_NAME]

    headers = []
    for col in range(2, 15):
        value = ws.cell(row=1, column=col).value
        try:
            headers.append(int(value))
        except (TypeError, ValueError):
            fail(f"Expected week number in {ws.cell(row=1, column=col).coordinate}; found {value!r}")
    if headers != list(range(1, WEEKS + 1)):
        fail(f"Week headers must be 1 through {WEEKS}; found {headers}")

    team_rows: dict[str, int] = {}
    for row in range(2, ws.max_row + 1):
        value = ws.cell(row=row, column=1).value
        if value is None:
            continue
        team = normalize_name(value)
        if team in CONFERENCE_TEAMS:
            if team in team_rows:
                fail(f"Conference team {team!r} appears more than once in column A.")
            team_rows[team] = row

    missing = sorted(CONFERENCE_TEAMS - set(team_rows))
    extra_count = len(team_rows) - len(CONFERENCE_TEAMS)
    if missing or extra_count:
        fail(f"Conference team rows do not match template. Missing={missing}; found={sorted(team_rows)}")

    entries: dict[tuple[str, int], dict] = {}
    opponent_classes: dict[str, tuple[bool, str | None]] = {}

    for team in sorted(CONFERENCE_TEAMS):
        row = team_rows[team]
        for week in range(1, WEEKS + 1):
            cell = ws.cell(row=row, column=week + 1)
            if cell.value is None or str(cell.value).strip() == "":
                continue

            opponent, location_hint = parse_opponent(cell.value)
            if not opponent:
                fail(f"{cell.coordinate}: opponent is blank after parsing.")
            if opponent == team:
                fail(f"{cell.coordinate}: {team} cannot play itself.")

            fill = normalized_fill(cell)
            if opponent in CONFERENCE_TEAMS:
                if fill in FILL_CLASSES:
                    fail(
                        f"{cell.coordinate}: conference matchup {team} vs {opponent} "
                        f"should be unfilled, not classification color #{fill}."
                    )
                classification = "conference"
            else:
                if fill not in FILL_CLASSES:
                    fail(
                        f"{cell.coordinate}: nonconference opponent {opponent!r} must use "
                        "yellow (#FFD966), blue (#4A86E8), or gray (#CCCCCC) fill."
                    )
                eligible, category = FILL_CLASSES[fill]
                classification = category if eligible else "ineligible"
                prior = opponent_classes.get(opponent)
                current = (eligible, category)
                if prior is not None and prior != current:
                    fail(
                        f"Opponent {opponent!r} has conflicting workbook classifications: "
                        f"{prior} vs {current}."
                    )
                opponent_classes[opponent] = current

            entries[(team, week)] = {
                "team": team,
                "week": week,
                "opponent": opponent,
                "location_hint": location_hint,
                "classification": classification,
                "cell": cell.coordinate,
            }

    # Every conference-vs-conference game must appear reciprocally in the same
    # week. This catches a mistyped opponent or a matchup placed in the wrong week.
    for (team, week), entry in entries.items():
        opponent = entry["opponent"]
        if opponent not in CONFERENCE_TEAMS:
            continue
        reciprocal = entries.get((opponent, week))
        if not reciprocal or reciprocal["opponent"] != team:
            fail(
                f"{entry['cell']}: {team} lists {opponent} in Week {week}, but "
                f"{opponent}'s Week {week} cell does not list {team}."
            )

    expected: dict[tuple[int, tuple[str, str]], dict] = {}
    for entry in entries.values():
        pair = tuple(sorted((entry["team"], entry["opponent"])))
        key = (entry["week"], pair)
        if key not in expected:
            expected[key] = {
                "week": entry["week"],
                "teams": pair,
                "hints": [],
                "source_cells": [],
            }
        expected[key]["hints"].append(
            {
                "team": entry["team"],
                "opponent": entry["opponent"],
                "location_hint": entry["location_hint"],
            }
        )
        expected[key]["source_cells"].append(entry["cell"])

    classifications = [
        {"opponent": opponent, "eligible": eligible, "category": category}
        for opponent, (eligible, category) in sorted(opponent_classes.items())
    ]
    return list(expected.values()), classifications


def fetch_espn_week(week: int, year: int) -> list[dict]:
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
    response = requests.get(
        url,
        params={
            "groups": ESPN_GROUP_ID,
            "week": week,
            "year": year,
            "seasontype": 2,
            "limit": 100,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("events", [])


def parse_espn_event(event: dict) -> dict:
    competition = event["competitions"][0]
    competitors = competition["competitors"]
    home = next(c for c in competitors if c["homeAway"] == "home")
    away = next(c for c in competitors if c["homeAway"] == "away")

    def team_name(row: dict) -> str:
        team = row["team"]
        return normalize_name(team.get("location") or team.get("displayName"))

    return {
        "home": team_name(home),
        "away": team_name(away),
        "kickoff_at": event["date"],
        "event_id": event.get("id"),
    }


def resolve_schedule(expected: list[dict], year: int) -> list[dict]:
    expected_by_week: dict[int, list[dict]] = defaultdict(list)
    for row in expected:
        expected_by_week[row["week"]].append(row)

    resolved: list[dict] = []
    errors: list[str] = []

    for week in range(1, WEEKS + 1):
        events = []
        for raw in fetch_espn_week(week, year):
            try:
                events.append(parse_espn_event(raw))
            except (KeyError, StopIteration, TypeError, ValueError) as exc:
                errors.append(f"Week {week} ESPN event {raw.get('id', 'unknown')}: {exc}")

        for item in expected_by_week.get(week, []):
            pair = set(item["teams"])
            matches = [
                event for event in events
                if {event["home"], event["away"]} == pair
            ]
            if len(matches) != 1:
                available = sorted(
                    f"{e['away']} @ {e['home']}"
                    for e in events
                    if e["home"] in CONFERENCE_TEAMS or e["away"] in CONFERENCE_TEAMS
                )
                errors.append(
                    f"Week {week} workbook matchup {item['teams'][0]} / {item['teams'][1]} "
                    f"matched {len(matches)} ESPN event(s). ESPN returned: {available}"
                )
                continue

            event = matches[0]

            # "at X" is an explicit road designation and should agree with ESPN.
            for hint in item["hints"]:
                if hint["location_hint"] == "away" and event["away"] != hint["team"]:
                    errors.append(
                        f"Week {week}: workbook says {hint['team']} is at {hint['opponent']}, "
                        f"but ESPN resolves {event['away']} @ {event['home']}."
                    )

            resolved.append(
                {
                    "week": week,
                    "away": event["away"],
                    "home": event["home"],
                    "kickoff_at": event["kickoff_at"],
                    "away_score": None,
                    "home_score": None,
                    "winner": None,
                }
            )

    if errors:
        for message in errors:
            print(f"::error::{message}", file=sys.stderr)
        fail(f"Schedule validation failed with {len(errors)} problem(s). No database changes were made.")

    # Defensive uniqueness check after ESPN resolution.
    keys = [(g["week"], g["away"], g["home"]) for g in resolved]
    if len(keys) != len(set(keys)):
        fail("Resolved schedule contains duplicate (week, away, home) games.")

    return sorted(resolved, key=lambda g: (g["week"], g["kickoff_at"], g["away"], g["home"]))


def supabase_headers(key: str) -> dict[str, str]:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def get_rows(base_url: str, key: str, table: str, params: dict) -> list[dict]:
    response = requests.get(
        f"{base_url}/rest/v1/{table}",
        headers=supabase_headers(key),
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def assert_unstarted_pool(base_url: str, service_key: str) -> None:
    players = get_rows(base_url, service_key, "players", {"select": "id", "limit": 1})
    picks = get_rows(base_url, service_key, "picks", {"select": "id", "limit": 1})
    if players or picks:
        fail(
            "Initialization is blocked because this Supabase project already has "
            "players or picks. Use a fresh preseason project; this workflow never "
            "rewrites a live pool."
        )


def clear_table(base_url: str, service_key: str, table: str) -> None:
    response = requests.delete(
        f"{base_url}/rest/v1/{table}",
        headers={
            **supabase_headers(service_key),
            "Prefer": "return=minimal",
        },
        params={"id": "not.is.null"} if table == "games" else {"opponent": "not.is.null"},
        timeout=30,
    )
    response.raise_for_status()


def insert_rows(base_url: str, service_key: str, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    response = requests.post(
        f"{base_url}/rest/v1/{table}",
        headers={
            **supabase_headers(service_key),
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        json=rows,
        timeout=30,
    )
    response.raise_for_status()


def write_generated_files(
    year: int,
    schedule_file: Path,
    games: list[dict],
    classifications: list[dict],
    supabase_url: str,
    anon_key: str,
) -> None:
    first_week = [g for g in games if g["week"] == 1]
    if not first_week:
        fail("Resolved schedule has no Week 1 games.")
    earliest = min(
        datetime.fromisoformat(g["kickoff_at"].replace("Z", "+00:00")).astimezone(CHICAGO)
        for g in first_week
    )
    pool_start = earliest.date() - timedelta(days=earliest.weekday())

    season = {
        "year": year,
        "weeks": WEEKS,
        "pool_start_date": pool_start.isoformat(),
        "conference": CONFERENCE,
        "schedule_file": schedule_file.name,
    }
    (ROOT / "season.json").write_text(json.dumps(season, indent=2) + "\n", encoding="utf-8")

    public_config = {
        "year": year,
        "weeks": WEEKS,
        "supabaseUrl": supabase_url,
        "supabaseAnonKey": anon_key,
    }
    (ROOT / "app-config.js").write_text(
        "// Generated by scripts/initialize_season.py.\n"
        "// Contains public browser configuration only; never add the service_role key.\n"
        f"window.SURVIVOR_APP_CONFIG = {json.dumps(public_config, indent=2)};\n",
        encoding="utf-8",
    )

    normalized = {
        "season": season,
        "games": games,
        "opponent_classification": classifications,
    }
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "normalized-schedule.json").write_text(
        json.dumps(normalized, indent=2) + "\n",
        encoding="utf-8",
    )


def verify_database(
    base_url: str,
    service_key: str,
    games: list[dict],
    classifications: list[dict],
) -> None:
    db_games = get_rows(
        base_url,
        service_key,
        "games",
        {"select": "week,away,home,kickoff_at", "order": "week.asc,kickoff_at.asc"},
    )
    db_classes = get_rows(
        base_url,
        service_key,
        "opponent_classification",
        {"select": "opponent,eligible,category", "order": "opponent.asc"},
    )

    expected_game_keys = {(g["week"], g["away"], g["home"]) for g in games}
    actual_game_keys = {(g["week"], g["away"], g["home"]) for g in db_games}
    if expected_game_keys != actual_game_keys:
        fail(
            "Post-write verification failed: games table does not exactly match "
            "the normalized workbook schedule."
        )

    expected_classes = {
        (r["opponent"], r["eligible"], r["category"]) for r in classifications
    }
    actual_classes = {
        (r["opponent"], r["eligible"], r["category"]) for r in db_classes
    }
    if expected_classes != actual_classes:
        fail(
            "Post-write verification failed: opponent_classification does not "
            "exactly match the workbook colors."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule-file", default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Parse workbook + resolve ESPN schedule, but do not write Supabase/config files.",
    )
    args = parser.parse_args()

    schedule_file = locate_schedule_file(args.schedule_file)
    year = infer_year(schedule_file, args.year)

    print(f"Initializing {CONFERENCE} Survivor {year} from {schedule_file.name}")
    expected, classifications = parse_workbook(schedule_file)
    print(f"  workbook validated: {len(expected)} unique game(s)")
    print(f"  workbook classified: {len(classifications)} unique nonconference opponent(s)")

    games = resolve_schedule(expected, year)
    print(f"  ESPN resolved: {len(games)} unique game(s) with kickoff timestamps")

    if args.validate_only:
        print("Validation-only mode: no database or repository config changes made.")
        return

    base_url = os.environ["SUPABASE_URL"].rstrip("/")
    anon_key = os.environ["SUPABASE_ANON_KEY"]
    service_key = os.environ["SUPABASE_SERVICE_KEY"]

    assert_unstarted_pool(base_url, service_key)

    # The project is known to be preseason/empty. Replace any bootstrap/test
    # schedule data atomically at the table level.
    clear_table(base_url, service_key, "games")
    clear_table(base_url, service_key, "opponent_classification")
    insert_rows(base_url, service_key, "opponent_classification", classifications)
    insert_rows(base_url, service_key, "games", games)

    verify_database(base_url, service_key, games, classifications)
    write_generated_files(
        year, schedule_file, games, classifications, base_url, anon_key
    )

    print(f"Initialization complete: {len(games)} games loaded for {year}.")
    print("Database verification passed.")
    print("Generated season.json, app-config.js, and data/normalized-schedule.json.")


if __name__ == "__main__":
    main()
