-- Store the dashboard summary algorithm version as data instead of a literal
-- repeated across six functions. A classification change in the app then only
-- bumps SUMMARY_ALGORITHM_VERSION in ui/dashboard_summary.py: the app writes
-- the new value here, every stored summary becomes stale, and the existing
-- background rebuild refreshes them. Previously a bump also needed a migration,
-- so logic fixes silently left old decisions on existing cards.

create table public.dashboard_summary_settings (
  singleton boolean primary key default true check (singleton),
  algorithm_version integer not null check (algorithm_version > 0),
  updated_at timestamptz not null default now()
);

insert into public.dashboard_summary_settings(singleton, algorithm_version) values (true, 2);

alter table public.dashboard_summary_settings enable row level security;
revoke all on public.dashboard_summary_settings from public, anon, authenticated;
grant select, update on public.dashboard_summary_settings to service_role;

create function public.dashboard_summary_algorithm_version()
returns integer
language sql
stable
security invoker
set search_path = ''
as $$
  select coalesce((select s.algorithm_version from public.dashboard_summary_settings s where s.singleton), 2)
$$;

create function public.dashboard_set_summary_algorithm_version(p_version integer)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if p_version is null or p_version < 1 then
    raise exception 'summary algorithm version must be a positive integer';
  end if;
  update public.dashboard_summary_settings
    set algorithm_version = p_version, updated_at = now()
    where singleton and algorithm_version is distinct from p_version;
  return public.dashboard_summary_algorithm_version();
end;
$$;

revoke all on function public.dashboard_summary_algorithm_version() from public, anon, authenticated;
revoke all on function public.dashboard_set_summary_algorithm_version(integer) from public, anon, authenticated;
grant execute on function public.dashboard_summary_algorithm_version() to service_role;
grant execute on function public.dashboard_set_summary_algorithm_version(integer) to service_role;

do $migration$
declare
  target record;
  definition text;
  updated_definition text;
  rewritten integer := 0;
begin
  for target in
    select p.oid, p.oid::regprocedure::text as signature
    from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname in (
        'dashboard_job_attention_page',
        'dashboard_job_detail',
        'dashboard_job_page',
        'dashboard_summary_next_batch',
        'dashboard_summary_selected_batch',
        'dashboard_summary_store_batch'
      )
  loop
    definition := pg_catalog.pg_get_functiondef(target.oid);
    updated_definition := replace(definition,
      'summary_algorithm_version <> 2',
      'summary_algorithm_version <> public.dashboard_summary_algorithm_version()');
    updated_definition := replace(updated_definition,
      'summary_algorithm_version = 2',
      'summary_algorithm_version = public.dashboard_summary_algorithm_version()');
    updated_definition := replace(updated_definition,
      $old$(r->>'summary_algorithm_version')::integer = 2$old$,
      $new$(r->>'summary_algorithm_version')::integer = public.dashboard_summary_algorithm_version()$new$);
    updated_definition := replace(updated_definition,
      $old$(r->>'job_revision')::bigint, 2,$old$,
      $new$(r->>'job_revision')::bigint, public.dashboard_summary_algorithm_version(),$new$);
    if updated_definition ~ 'summary_algorithm_version(\s*|\)::integer\s*)(=|<>)\s*[0-9]'
       or updated_definition ~ $re$\(r->>'job_revision'\)::bigint, [0-9]+,$re$ then
      raise exception 'A hard-coded dashboard summary version literal remains in %', target.signature;
    end if;
    if updated_definition is distinct from definition then
      execute updated_definition;
      rewritten := rewritten + 1;
    end if;
  end loop;
  if rewritten <> 6 then
    raise exception 'Expected to rewrite 6 dashboard summary functions, rewrote %', rewritten;
  end if;
end;
$migration$;
