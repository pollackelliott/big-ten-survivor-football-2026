-- ============================================================================
-- Big Ten Survivor 2026 — Supabase schema
-- Run this once in the Supabase SQL editor on a fresh project.
--
-- IDENTITY MODEL: players are real Supabase Auth users (email + password).
-- Supabase handles sessions, login, and password resets natively — there is
-- no homegrown token/password scheme in this database at all. A player's
-- row in `players` shares its id with their row in Supabase's own
-- `auth.users`, created automatically by a trigger the moment they sign up.
-- ============================================================================

create extension if not exists pgcrypto;

-- ----------------------------------------------------------------------------
-- TABLES
-- ----------------------------------------------------------------------------

create table players (
  id          uuid primary key references auth.users(id) on delete cascade,
  name        text not null unique,   -- display name, separate from their login email
  fan_of      text,                    -- optional, set only at Week 1 signup
  created_at  timestamptz not null default now()
);

create table games (
  id          bigint generated always as identity primary key,
  week        int not null,
  away        text not null,
  home        text not null,
  kickoff_at  timestamptz not null,
  away_score  int,
  home_score  int,
  winner      text, -- set once final; null while in progress / not started
  updated_at  timestamptz not null default now(),
  unique (week, away, home)
);

create table picks (
  id             bigint generated always as identity primary key,
  player_id      uuid not null references players(id) on delete cascade,
  week           int not null,
  team           text not null,
  last_edited_by text not null default 'player' check (last_edited_by in ('player','commissioner')),
  admin_note     text,
  updated_at     timestamptz not null default now(),
  unique (player_id, week)
);

-- Opponent classification is keyed on the OPPONENT alone (Rule 3 only looks at
-- the opponent's own conference), not on the conference-team/opponent pairing.
-- If an opponent isn't in this table, it isn't a valid non-conference opponent
-- this season for any Big Ten team (add it here if that ever comes up).
create table opponent_classification (
  opponent  text primary key,
  eligible  boolean not null,       -- false = FCS / not FBS, cannot be picked at all
  category  text check (category in ('g5','not_g5'))  -- null when not eligible
);

-- Anyone who should get commissioner powers. Populated after you create a
-- Supabase Auth user for yourself (see SETUP.md).
create table admins (
  user_id uuid primary key references auth.users(id)
);

-- ----------------------------------------------------------------------------
-- SEED DATA: 2026 non-conference opponent classification
-- (verified against 2026 conference realignment; new Pac-12 = G5 per ruling)
-- ----------------------------------------------------------------------------

insert into opponent_classification (opponent, eligible, category) values
  -- Not G5 (ACC / Big 12 / SEC / Notre Dame — the "other power" bucket, now
  -- that Big Ten is the pool's own conference)
  ('California',       true, 'not_g5'),
  ('Boston College',    true, 'not_g5'),
  ('Wake Forest',       true, 'not_g5'),
  ('Duke',              true, 'not_g5'),
  ('Virginia Tech',     true, 'not_g5'),
  ('Notre Dame',        true, 'not_g5'),
  ('Oklahoma',          true, 'not_g5'),
  ('Mississippi State', true, 'not_g5'),
  ('Texas',             true, 'not_g5'),
  ('Oklahoma State',    true, 'not_g5'),
  ('Iowa State',        true, 'not_g5'),
  ('Colorado',          true, 'not_g5'),

  -- G5 (American, MAC, Mountain West, Sun Belt, C-USA, new Pac-12, and
  -- FBS independents other than Notre Dame, per ruling)
  ('UAB',               true, 'g5'),
  ('North Texas',       true, 'g5'),
  ('Temple',            true, 'g5'),
  ('Toledo',            true, 'g5'),
  ('Ball State',        true, 'g5'),
  ('Western Michigan',  true, 'g5'),
  ('Eastern Michigan',  true, 'g5'),
  ('Bowling Green',     true, 'g5'),
  ('Kent State',        true, 'g5'),
  ('Akron',             true, 'g5'),
  ('Buffalo',           true, 'g5'),
  ('Ohio',              true, 'g5'),
  ('Fresno State',      true, 'g5'),
  ('Utah State',        true, 'g5'),
  ('San Diego State',   true, 'g5'),
  ('Nevada',            true, 'g5'),
  ('Northern Illinois', true, 'g5'),
  ('UTEP',              true, 'g5'),
  ('Marshall',          true, 'g5'),
  ('Louisiana',         true, 'g5'),
  ('Western Kentucky',  true, 'g5'),
  ('Boise State',       true, 'g5'),
  ('Washington State',  true, 'g5'),
  ('UMass',             true, 'g5'),
  ('UConn',             true, 'g5'),

  -- Not eligible (FCS opponents — Rule 1, cannot be picked at all)
  ('Eastern Illinois',    false, null),
  ('Indiana State',       false, null),
  ('South Dakota State',  false, null),
  ('Hampton',             false, null),
  ('Howard',              false, null),
  ('Western Illinois',    false, null),
  ('Portland State',      false, null),
  ('Southern Illinois',   false, null),
  ('Northern Iowa',       false, null),
  ('North Dakota',        false, null),
  ('Eastern Washington',  false, null);

-- ----------------------------------------------------------------------------
-- AUTO-CREATE a players row the instant someone signs up via Supabase Auth.
-- The display name and favorite team travel in as signUp() metadata; see
-- the frontend's signup call for the exact shape.
-- ----------------------------------------------------------------------------

create or replace function handle_new_player() returns trigger as $$
begin
  insert into public.players (id, name, fan_of)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'name', split_part(new.email, '@', 1)),
    nullif(new.raw_user_meta_data->>'fan_of', '')
  );
  return new;
end;
$$ language plpgsql security definer;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_player();

-- ----------------------------------------------------------------------------
-- HELPERS
-- ----------------------------------------------------------------------------

create or replace function week_deadline(p_week int) returns timestamptz as $$
declare
  d date;
begin
  select (min(kickoff_at) at time zone 'America/Chicago')::date into d
  from games where week = p_week;

  if d is null then
    return null;
  end if;

  d := d + ((6 - extract(dow from d)::int + 7) % 7);

  return (d::timestamp + interval '10 hours 59 minutes') at time zone 'America/Chicago';
end;
$$ language plpgsql stable;

create or replace function opponent_of(p_week int, p_team text) returns text as $$
  select case when home = p_team then away
              when away = p_team then home
              else null end
  from games where week = p_week and (home = p_team or away = p_team);
$$ language sql stable;

create or replace function classify_pick(p_week int, p_team text) returns text as $$
declare
  v_opp text;
  v_conf_teams text[] := array[
    'Illinois','Indiana','Iowa','Maryland','Michigan','Michigan State','Minnesota',
    'Nebraska','Northwestern','Ohio State','Oregon','Penn State','Purdue','Rutgers',
    'UCLA','USC','Washington','Wisconsin'
  ];
  v_row opponent_classification%rowtype;
begin
  v_opp := opponent_of(p_week, p_team);
  if v_opp is null then
    return 'invalid';
  end if;
  if v_opp = any(v_conf_teams) then
    return 'conference';
  end if;
  select * into v_row from opponent_classification where opponent = v_opp;
  if not found or not v_row.eligible then
    return 'ineligible';
  end if;
  return v_row.category;
end;
$$ language plpgsql stable;

create or replace function pick_editable_until(p_week int, p_team text) returns timestamptz as $$
  select least(g.kickoff_at, week_deadline(p_week))
  from games g where g.week = p_week and (g.home = p_team or g.away = p_team);
$$ language sql stable;

create or replace function pick_result(p_week int, p_team text) returns int as $$
  select case
    when g.winner is null then null
    when g.winner = p_team then 1
    else 0
  end
  from games g where g.week = p_week and (g.home = p_team or g.away = p_team);
$$ language sql stable;

create or replace function week_reopen_time(p_week int) returns timestamptz as $$
declare
  wd timestamptz;
begin
  wd := week_deadline(p_week);
  if wd is null then return null; end if;
  return (((wd at time zone 'America/Chicago')::date + 1)::timestamp + interval '5 hours')
         at time zone 'America/Chicago';
end;
$$ language plpgsql stable;

-- ----------------------------------------------------------------------------
-- CORE WRITE PATH: submit_pick
-- Identity comes from auth.uid() — the caller's real, verified Supabase
-- Auth session — not a hand-rolled token anymore.
-- ----------------------------------------------------------------------------

create or replace function submit_pick(
  p_week int,
  p_team text
) returns void as $$
declare
  v_player_id     uuid := auth.uid();
  v_category      text;
  v_new_deadline  timestamptz;
  v_old           record;
  v_old_deadline  timestamptz;
  v_already_used  boolean;
  v_nonconf_used  int;
  v_g5_used       int;
begin
  if v_player_id is null then
    raise exception 'not authenticated';
  end if;

  if exists(
    select 1 from picks p
    where p.player_id = v_player_id and p.week < p_week
      and pick_result(p.week, p.team) = 0
  ) then
    raise exception 'you have been eliminated and can no longer submit picks';
  end if;

  if exists(
    select 1 from picks p
    where p.player_id = v_player_id and p.week < p_week
      and pick_result(p.week, p.team) is null
  ) then
    raise exception 'your previous week has not been decided yet';
  end if;

  if p_week > 1 then
    declare
      v_reopen timestamptz := week_reopen_time(p_week - 1);
    begin
      if v_reopen is not null and now() < v_reopen then
        raise exception 'next week''s picks open Sunday at 5:00am';
      end if;
    end;
  end if;

  v_category := classify_pick(p_week, p_team);
  if v_category = 'invalid' then
    raise exception 'no such game this week for that team';
  end if;
  if v_category = 'ineligible' then
    raise exception 'that opponent is not FBS and cannot be picked';
  end if;

  v_new_deadline := pick_editable_until(p_week, p_team);
  if now() >= v_new_deadline then
    raise exception 'that game has already locked';
  end if;

  select * into v_old from picks where player_id = v_player_id and week = p_week;
  if found then
    v_old_deadline := pick_editable_until(v_old.week, v_old.team);
    if v_old_deadline is not null and now() >= v_old_deadline then
      raise exception 'your current pick for this week is already locked';
    end if;
  end if;

  select exists(
    select 1 from picks where player_id = v_player_id and team = p_team and week <> p_week
  ) into v_already_used;
  if v_already_used then
    raise exception 'you have already picked that team this season';
  end if;

  if v_category in ('g5','not_g5') then
    select count(*) into v_nonconf_used
    from picks p
    where p.player_id = v_player_id and p.week <> p_week
      and classify_pick(p.week, p.team) in ('g5','not_g5');

    if v_nonconf_used >= 3 then
      raise exception 'non-conference pick limit (3) already used';
    end if;
  end if;

  if v_category = 'g5' then
    select count(*) into v_g5_used
    from picks p
    where p.player_id = v_player_id and p.week <> p_week
      and classify_pick(p.week, p.team) = 'g5';

    if v_g5_used >= 1 then
      raise exception 'G5 pick limit (1) already used';
    end if;
  end if;

  insert into picks (player_id, week, team, last_edited_by, admin_note, updated_at)
  values (v_player_id, p_week, p_team, 'player', null, now())
  on conflict (player_id, week)
  do update set team = excluded.team, last_edited_by = 'player', admin_note = null, updated_at = now();
end;
$$ language plpgsql security definer;

-- ----------------------------------------------------------------------------
-- READS
-- ----------------------------------------------------------------------------

create view players_public as select id, name, fan_of, created_at from players;

create or replace function get_public_board() returns table(
  player_id   uuid,
  player_name text,
  week        int,
  team        text,
  revealed    boolean
) as $$
  select
    p.id,
    p.name,
    pk.week,
    case when now() >= week_deadline(pk.week) then pk.team else null end,
    coalesce(now() >= week_deadline(pk.week), false)
  from players p
  join picks pk on pk.player_id = p.id;
$$ language sql stable security definer;

create or replace function get_my_picks() returns table(
  week            int,
  team            text,
  category        text,
  editable_until  timestamptz
) as $$
declare
  v_player_id uuid := auth.uid();
begin
  if v_player_id is null then
    raise exception 'not authenticated';
  end if;

  return query
    select pk.week, pk.team, classify_pick(pk.week, pk.team), pick_editable_until(pk.week, pk.team)
    from picks pk
    where pk.player_id = v_player_id
    order by pk.week;
end;
$$ language plpgsql stable security definer;

-- ----------------------------------------------------------------------------
-- COMMISSIONER (admin) functions — unchanged by the identity rework.
-- ----------------------------------------------------------------------------

create or replace function admin_get_all_picks() returns table(
  player_id   uuid,
  player_name text,
  week        int,
  team        text,
  last_edited_by text,
  admin_note  text,
  updated_at  timestamptz
) as $$
  select p.id, p.name, pk.week, pk.team, pk.last_edited_by, pk.admin_note, pk.updated_at
  from picks pk
  join players p on p.id = pk.player_id
  where exists(select 1 from admins where user_id = auth.uid())
  order by p.name, pk.week;
$$ language sql stable security definer;

create or replace function admin_set_pick(
  p_player_id uuid,
  p_week      int,
  p_team      text,
  p_note      text default null
) returns void as $$
begin
  if not exists(select 1 from admins where user_id = auth.uid()) then
    raise exception 'not authorized';
  end if;

  insert into picks (player_id, week, team, last_edited_by, admin_note, updated_at)
  values (p_player_id, p_week, p_team, 'commissioner', p_note, now())
  on conflict (player_id, week)
  do update set team = excluded.team, last_edited_by = 'commissioner',
                admin_note = excluded.admin_note, updated_at = now();
end;
$$ language plpgsql security definer;

create or replace function admin_delete_pick(p_player_id uuid, p_week int) returns void as $$
begin
  if not exists(select 1 from admins where user_id = auth.uid()) then
    raise exception 'not authorized';
  end if;

  delete from picks where player_id = p_player_id and week = p_week;
end;
$$ language plpgsql security definer;

-- ----------------------------------------------------------------------------
-- LOCKDOWN
-- ----------------------------------------------------------------------------

alter table players enable row level security;
alter table picks enable row level security;
alter table games enable row level security;
alter table opponent_classification enable row level security;
alter table admins enable row level security;

create policy "games are public" on games for select using (true);
create policy "classification is public" on opponent_classification for select using (true);

grant usage on schema public to anon, authenticated;
grant select on games, opponent_classification, players_public to anon, authenticated;
grant execute on function
  get_public_board, classify_pick, opponent_of, pick_editable_until, week_deadline
  to anon, authenticated;
grant execute on function submit_pick, get_my_picks to authenticated;
grant execute on function admin_get_all_picks, admin_set_pick, admin_delete_pick to authenticated;
