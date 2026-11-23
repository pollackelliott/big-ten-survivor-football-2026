# Big Ten Survivor Football — New Season Setup

This branch is the reusable football engine preserved from the completed 2026 pool.

The goal is deliberately simple: **the commissioner's P4G5 Excel workbook is the season-definition file.** Do not convert it to CSV or manually seed the schedule.

## What stays the same

The workbook must use the proven layout:

- Sheet name: `P4G5`
- Column A: conference teams
- Row 1, columns B:N: Weeks 1–13
- Cells contain opponents, optionally prefixed by `at ` or `vs. `
- Yellow fill (`#FFD966`) = power-conference nonconference opponent
- Blue fill (`#4A86E8`) = G5 opponent
- Gray fill (`#CCCCCC`) = FCS / ineligible opponent
- Unfilled cells = conference games
- Blank cells = bye

Recommended filename: `2027 Big Ten Football Schedule Grid.xlsx`.

The initializer validates the workbook before writing anything. It checks team rows, week headers, reciprocal conference matchups, classification fills, duplicate games, ESPN matchup agreement, and road-game `at` notation.

## 1. Start the new season repo

Create the new season repository from this `template/football-next-season` branch.

Do **not** build from the archived `main` branch; `main` is the historical 2026 museum site.

## 2. Create a fresh Supabase project

Create a new Supabase project for this pool.

In the Supabase SQL Editor, run the full current contents of:

`supabase/schema.sql`

The reusable schema intentionally contains no season-specific opponent seed rows. Those are generated from the workbook colors.

Turn off email confirmation for the pool's normal self-service signup flow, matching the proven 2026 setup.

## 3. Create the commissioner account

Create the commissioner user in Supabase Auth, copy its UUID, then run:

```sql
insert into public.admins (user_id)
values ('PASTE-COMMISSIONER-UUID-HERE');
```

## 4. Add GitHub Actions secrets

Add these repository secrets:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY` — the public anon/client key
- `SUPABASE_SERVICE_KEY` — the private service-role key

The service-role key is used only by GitHub Actions and must never be put into browser code.

## 5. Upload the schedule workbook

Put the completed Excel workbook in the repository's `data/` folder.

Normally there should be exactly one `.xlsx` workbook there.

## 6. Initialize the season

Open:

**GitHub → Actions → Initialize Football Season → Run workflow**

Usually both inputs can be left blank:

- the year is inferred from the workbook filename when it contains `20XX`;
- the workbook is inferred when it is the only `.xlsx` file in `data/`.

The workflow will:

1. validate the workbook;
2. read its P4/G5/FCS color classifications;
3. match every game against ESPN;
4. resolve canonical home/away and exact kickoff timestamps;
5. refuse to proceed if the Supabase project already contains players or picks;
6. load the `games` table;
7. load `opponent_classification`;
8. verify the database exactly matches the normalized workbook;
9. generate `season.json`;
10. generate browser-safe `app-config.js`;
11. save `data/normalized-schedule.json` as an auditable normalized copy.

If validation fails, fix the workbook or a deliberate name alias and rerun it. A validation failure occurs before schedule data is written.

## 7. Turn on GitHub Pages and test

Deploy GitHub Pages from `main`, root folder, as in 2026.

Before opening signups:

- confirm the Picks Grid shows the expected schedule;
- inspect a few Thursday/Friday games to confirm kickoff locking;
- inspect P4/G5/FCS eligibility;
- test signup and Week 1 submission;
- test commissioner login.

## 8. Normal season operation

The existing **Update Big Ten Survivor scores** workflow reads `season.json`, so it no longer contains hardcoded 2026 dates or year values.

The final 2026 rules are preserved in the reusable engine, including:

- one team may be used only once;
- nonconference/G5 limits;
- FCS opponents are ineligible;
- Saturday 10:59am Central reveal/lock;
- earlier Thursday/Friday kickoff locks;
- missed-pick elimination;
- final-week dead-man switch preserving a lone winner or a zero-survivor finish.
