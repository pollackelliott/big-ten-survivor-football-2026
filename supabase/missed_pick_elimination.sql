-- Missing a weekly pick by the normal Saturday 10:59am CT reveal is an elimination.
-- Dead-man switch: once every player alive entering a week has a final outcome,
-- the pool ends immediately if zero or one survivors remain. Later empty weeks
-- must never eliminate a lone winner or reopen a pool with no survivors.

create or replace function public.pool_end_week()
returns integer
language plpgsql
stable
security definer
set search_path = 'public'
as $function$
declare
  v_week integer;
  v_player_id uuid;
  v_active uuid[];
  v_next_active uuid[];
  v_team text;
  v_result integer;
  v_pending boolean;
begin
  select array_agg(p.id order by p.id)
  into v_active
  from public.players p;

  if coalesce(array_length(v_active, 1), 0) = 0 then
    return null;
  end if;

  for v_week in
    select distinct g.week
    from public.games g
    order by g.week
  loop
    v_next_active := array[]::uuid[];
    v_pending := false;

    foreach v_player_id in array v_active
    loop
      select pk.team
      into v_team
      from public.picks pk
      where pk.player_id = v_player_id
        and pk.week = v_week;

      if v_team is null then
        if now() >= public.week_deadline(v_week) then
          null; -- missed deadline: eliminated this week
        else
          v_pending := true;
          v_next_active := array_append(v_next_active, v_player_id);
        end if;
      else
        v_result := public.pick_result(v_week, v_team);

        if v_result = 1 then
          v_next_active := array_append(v_next_active, v_player_id);
        elsif v_result = 0 then
          null; -- losing pick: eliminated this week
        else
          v_pending := true;
          v_next_active := array_append(v_next_active, v_player_id);
        end if;
      end if;
    end loop;

    -- Do not crown a temporary lone survivor while another finalist's
    -- outcome for this same week is still unresolved.
    if v_pending then
      return null;
    end if;

    v_active := v_next_active;

    if coalesce(array_length(v_active, 1), 0) <= 1 then
      return v_week;
    end if;
  end loop;

  return null;
end;
$function$;

revoke all on function public.pool_end_week() from public, anon, authenticated;

create or replace function public.player_eliminated_week(p_player_id uuid)
returns integer
language sql
stable
security definer
set search_path = 'public'
as $function$
  with cutoff as (
    select public.pool_end_week() as end_week
  )
  select min(w.week)::integer
  from (
    select distinct g.week
    from public.games g
  ) w
  cross join cutoff c
  left join public.picks pk
    on pk.player_id = p_player_id
   and pk.week = w.week
  where w.week <= coalesce(c.end_week, 2147483647)
    and (
      (
        now() >= public.week_deadline(w.week)
        and pk.player_id is null
      )
      or (
        pk.player_id is not null
        and public.pick_result(w.week, pk.team) = 0
      )
    );
$function$;

revoke all on function public.player_eliminated_week(uuid) from public;

create or replace function public.submit_pick(p_week integer, p_team text)
returns void
language plpgsql
security definer
as $function$
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

  if public.pool_end_week() is not null then
    raise exception 'the pool has ended';
  end if;

  if public.player_eliminated_week(v_player_id) is not null then
    raise exception 'you have been eliminated and can no longer submit picks';
  end if;

  if exists(
    select 1 from public.picks p
    where p.player_id = v_player_id and p.week < p_week
      and public.pick_result(p.week, p.team) is null
  ) then
    raise exception 'your previous week has not been decided yet';
  end if;

  if p_week > 1 then
    declare
      v_reopen timestamptz := public.week_reopen_time(p_week - 1);
    begin
      if v_reopen is not null and now() < v_reopen then
        raise exception 'next week''s picks open Sunday at 5:00am';
      end if;
    end;
  end if;

  v_category := public.classify_pick(p_week, p_team);
  if v_category = 'invalid' then
    raise exception 'no such game this week for that team';
  end if;
  if v_category = 'ineligible' then
    raise exception 'that opponent is not FBS and cannot be picked';
  end if;

  v_new_deadline := public.pick_editable_until(p_week, p_team);
  if now() >= v_new_deadline then
    raise exception 'that game has already locked';
  end if;

  select * into v_old from public.picks where player_id = v_player_id and week = p_week;
  if found then
    v_old_deadline := public.pick_editable_until(v_old.week, v_old.team);
    if v_old_deadline is not null and now() >= v_old_deadline then
      raise exception 'your current pick for this week is already locked';
    end if;
  end if;

  select exists(
    select 1 from public.picks where player_id = v_player_id and team = p_team and week <> p_week
  ) into v_already_used;
  if v_already_used then
    raise exception 'you have already picked that team this season';
  end if;

  if v_category in ('g5','not_g5') then
    select count(*) into v_nonconf_used
    from public.picks p
    where p.player_id = v_player_id and p.week <> p_week
      and public.classify_pick(p.week, p.team) in ('g5','not_g5');

    if v_nonconf_used >= 3 then
      raise exception 'non-conference pick limit (3) already used';
    end if;
  end if;

  if v_category = 'g5' then
    select count(*) into v_g5_used
    from public.picks p
    where p.player_id = v_player_id and p.week <> p_week
      and public.classify_pick(p.week, p.team) = 'g5';

    if v_g5_used >= 1 then
      raise exception 'G5 pick limit (1) already used';
    end if;
  end if;

  insert into public.picks (player_id, week, team, last_edited_by, admin_note, updated_at)
  values (v_player_id, p_week, p_team, 'player', null, now())
  on conflict (player_id, week)
  do update set team = excluded.team, last_edited_by = 'player', admin_note = null, updated_at = now();
end;
$function$;

create or replace function public.admin_get_missing_pick_email_list()
returns table(
  week integer,
  player_count bigint,
  emails text
)
language plpgsql
stable
security definer
set search_path = 'public', 'auth'
as $function$
declare
  v_week integer;
  v_end_week integer;
begin
  if not exists (
    select 1
    from public.admins a
    where a.user_id = auth.uid()
  ) then
    raise exception 'not authorized';
  end if;

  v_end_week := public.pool_end_week();
  if v_end_week is not null then
    return query select v_end_week, 0::bigint, ''::text;
    return;
  end if;

  select max(g.week)::integer
  into v_week
  from (
    select distinct gm.week
    from public.games gm
  ) g
  where g.week = 1
     or now() >= public.week_reopen_time(g.week - 1);

  return query
  with missing_alive as (
    select pl.id, pl.name, u.email
    from public.players pl
    join auth.users u on u.id = pl.id
    where public.player_eliminated_week(pl.id) is null
      and not exists (
        select 1
        from public.picks pk
        where pk.player_id = pl.id
          and pk.week = v_week
      )
  )
  select
    v_week,
    count(*)::bigint,
    coalesce(string_agg(m.email, ', ' order by m.name), '')
  from missing_alive m
  where m.email is not null;
end;
$function$;
