# Big Ten Survivor 2026 — Deployment Guide

This is the same proven stack as the SEC pool — a **separate** Supabase
project and a **separate** GitHub repo, so the two pools never share data,
credentials, or risk of one affecting the other.

## 1. Create the Supabase project
1. Go to supabase.com → New project. Note the **Project URL** and, under
   Settings → API, the **anon public key** and the **service_role key**
   (keep the service_role key secret — it's never used in the browser).
2. Open the SQL Editor → paste in the entire contents of `supabase/schema.sql`
   → Run. This creates every table, the Big Ten opponent classification seed
   data, and all the RPC functions in one shot.

## 2. Turn off email confirmation
Same as SEC: Authentication → Sign In / Providers → Email → turn off
**"Confirm email"** → save. This is what makes signup log someone in
immediately, with no confirmation email step.

## 3. Create your commissioner account
1. Authentication → Users → Add user. You can reuse the exact same email and
   password you use for the SEC pool's commissioner account if you want it
   to feel identical — it's a separate account under the hood either way,
   since Supabase Auth accounts are scoped per-project.
2. Copy that user's UUID.
3. SQL Editor, new query:
   ```sql
   insert into admins (user_id) values ('paste-your-uuid-here');
   ```

## 4. Wire up the frontend
Open `index.html` and fill in the two placeholders near the top of the
`<script>` block:
```js
const SUPABASE_URL = 'YOUR-BIGTEN-SUPABASE-URL';
const SUPABASE_ANON_KEY = 'YOUR-BIGTEN-ANON-KEY';
```

## 5. Set up the GitHub repo
1. Push this whole folder to a new repo: **big-ten-survivor-football-2026**.
2. Repo → Settings → Secrets and variables → Actions → add:
   - `SUPABASE_URL` — this project's URL
   - `SUPABASE_SERVICE_KEY` — this project's service_role key
3. Repo → Settings → Pages → deploy from `main`, root folder.
4. The workflow auto-detects the current week from Sept 5, 2026 (Big Ten's
   own Week 1 Saturday — same date as SEC's this year, coincidentally).

## 6. Load the schedule
Same as SEC: Actions tab → "Update Big Ten Survivor scores" → Run workflow →
type a week number → Run. Repeat for weeks 1–13 to backfill the full season
schedule ahead of time, same as we did for SEC.

**One thing to verify on the very first run:** the scraper uses ESPN's
group id `12` for the Big Ten, based on a community-sourced ID list rather
than anything Anthropic could verify directly — the same way SEC's `8` was
never independently confirmed until you actually ran it and saw real SEC
teams come back. Check the first real run's log line
(`found N Big Ten-involved game(s)`) and glance at the `games` table in
Supabase to confirm the teams that came back are genuinely Big Ten
opponents — if the number turns out to be wrong, it's a one-line fix in
`scripts/update_scores.py`.

## 7. Everything else
Identical to the SEC pool: self-serve signup, dynamic pick menu, hidden
Saturday-11am reveal, Sunday-5am freeze/reopen, elimination logic,
commissioner tools, and the automated GitHub Actions score pipeline. No
code differs in how any of that works — only the team roster, colors,
opponent classification, background color, and page copy are different.
