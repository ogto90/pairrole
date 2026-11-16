-- Profile edits may change eligibility for unhandled listings. Keep already
-- rated, archived, ignored, or applied listings on their saved decision until
-- the user explicitly revisits them.
create or replace function public.dashboard_summary_profile_refresh_needed(
  p_user_id uuid,
  p_job_id bigint
)
returns boolean
language sql
stable
security invoker
set search_path = ''
as $$
  select not (
    coalesce((
      select a.status
      from public.applications a
      where a.user_id = p_user_id and a.job_id = p_job_id
      order by a.updated_at desc, a.id desc
      limit 1
    ), '') in ('applied','interview','offer','hired','rejected','withdrawn','no_response')
    or coalesce((
      select r.status
      from public.job_reviews r
      where r.user_id = p_user_id and r.job_id = p_job_id
      order by r.updated_at desc, r.id desc
      limit 1
    ), '') in ('rated','ignored','archived')
    or exists (
      select 1 from public.job_match_assessments a
      where a.user_id = p_user_id and a.job_id = p_job_id and a.fit_score is not null
    )
  );
$$;

revoke all on function public.dashboard_summary_profile_refresh_needed(uuid,bigint)
  from public, anon, authenticated;
grant execute on function public.dashboard_summary_profile_refresh_needed(uuid,bigint)
  to service_role;

-- Keep the current worker and page RPC definitions intact, changing only the
-- profile-revision checks. Other dependencies (job edits, algorithm versions,
-- per-listing evidence) continue to invalidate handled summaries as before.
do $migration$
declare
  f record;
  definition text;
  updated_definition text;
  stale_expression constant text := 'or s.profile_revision is distinct from us.profile_revision';
  current_expression constant text := 'and s.profile_revision = us.profile_revision';
  stale_replacement constant text := 'or (s.profile_revision is distinct from us.profile_revision and public.dashboard_summary_profile_refresh_needed(p_user_id, j.id))';
  current_replacement constant text := 'and (s.profile_revision = us.profile_revision or not public.dashboard_summary_profile_refresh_needed(p_user_id, j.id))';
  stale_count integer;
  current_count integer;
  changed_functions integer := 0;
begin
  for f in
    select p.oid, p.proname
    from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname in (
        'dashboard_summary_next_batch', 'dashboard_summary_selected_batch',
        'dashboard_job_page', 'dashboard_job_attention_page', 'dashboard_job_detail'
      )
  loop
    definition := pg_catalog.pg_get_functiondef(f.oid);
    updated_definition := definition;
    stale_count := (length(updated_definition) - length(replace(updated_definition, stale_expression, ''))) / length(stale_expression);
    if f.proname in ('dashboard_summary_next_batch','dashboard_summary_selected_batch','dashboard_job_page','dashboard_job_attention_page') then
      if stale_count <> 1 then
        raise exception 'Expected one profile stale check in %, found %', f.proname, stale_count;
      end if;
      updated_definition := replace(updated_definition, stale_expression, stale_replacement);
    elsif stale_count <> 0 then
      raise exception 'Unexpected profile stale check in %', f.proname;
    end if;

    current_count := (length(updated_definition) - length(replace(updated_definition, current_expression, ''))) / length(current_expression);
    if f.proname in ('dashboard_job_page','dashboard_job_attention_page','dashboard_job_detail') then
      if current_count <> 1 then
        raise exception 'Expected one current-summary profile check in %, found %', f.proname, current_count;
      end if;
      updated_definition := replace(updated_definition, current_expression, current_replacement);
    elsif current_count <> 0 then
      raise exception 'Unexpected current-summary profile check in %', f.proname;
    end if;
    execute updated_definition;
    changed_functions := changed_functions + 1;
  end loop;
  if changed_functions <> 5 then
    raise exception 'Expected five dashboard functions to be updated, found %', changed_functions;
  end if;
end;
$migration$;
