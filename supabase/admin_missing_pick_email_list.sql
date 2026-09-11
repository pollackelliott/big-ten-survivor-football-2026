-- Commissioner-only helper used by the website to copy a BCC-ready list of
-- alive players who have not submitted the currently open week's pick.
create or replace function public.admin_get_missing_pick_email_list()
returns table(week integer, player_count bigint, emails text)
language plpgsql
stable
security definer
set search_path = public, auth
as $function$
declare
  v_week integer;
begin
  if not exists (select 1 from public.admins a where a.user_id = auth.uid()) then
    raise exception 'not authorized';
  end if;

  select max(g.week)::integer into v_week
  from (select distinct gm.week from public.games gm) g
  where g.week = 1 or now() >= public.week_reopen_time(g.week - 1);

  return query
  with missing_alive as (
    select pl.id, pl.name, u.email
    from public.players pl
    join auth.users u on u.id = pl.id
    where not exists (
      select 1 from generate_series(1, v_week - 1) as prior(week)
      where not exists (
        select 1 from public.picks pk
        where pk.player_id = pl.id and pk.week = prior.week
      )
    )
    and not exists (
      select 1 from public.picks pk
      where pk.player_id = pl.id
        and pk.week < v_week
        and public.pick_result(pk.week, pk.team) = 0
    )
    and not exists (
      select 1 from public.picks pk
      where pk.player_id = pl.id and pk.week = v_week
    )
  )
  select v_week, count(*)::bigint,
         coalesce(string_agg(m.email, ', ' order by m.name), '')
  from missing_alive m
  where m.email is not null;
end;
$function$;

revoke all on function public.admin_get_missing_pick_email_list() from public;
grant execute on function public.admin_get_missing_pick_email_list() to authenticated;
