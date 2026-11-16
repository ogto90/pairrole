-- A missing entry in p_failed_fingerprints means the latest Fit attempt did not
-- fail. PostgreSQL's JSON operator returns NULL for a missing key, though, and
-- `NOT NULL` made otherwise eligible rows disappear from Ready to rate.
-- Patch the two page RPCs while preserving their current full definitions and
-- grants; fail the migration if either definition has drifted unexpectedly.
DO $migration$
DECLARE
  target_function regprocedure;
  function_definition text;
  old_expression constant text := '(p_failed_fingerprints->>s.job_id::text = s.summary->>''fit_fingerprint'') as rating_failed';
  new_expression constant text := 'coalesce((p_failed_fingerprints->>s.job_id::text = s.summary->>''fit_fingerprint''), false) as rating_failed';
  replaced_definition text;
BEGIN
  FOREACH target_function IN ARRAY ARRAY[
    'public.dashboard_job_attention_page(uuid,text,text,integer,text,text,text,integer,integer,jsonb,integer)'::regprocedure,
    'public.dashboard_job_page(uuid,text,text,integer,text,text,text,integer,integer,jsonb,integer)'::regprocedure
  ] LOOP
    function_definition := pg_get_functiondef(target_function);
    IF position(old_expression IN function_definition) = 0 THEN
      RAISE EXCEPTION 'Expected rating_failed expression not found in %', target_function;
    END IF;
    IF (length(function_definition) - length(replace(function_definition, old_expression, ''))) / length(old_expression) <> 1 THEN
      RAISE EXCEPTION 'Expected exactly one rating_failed expression in %', target_function;
    END IF;
    replaced_definition := replace(function_definition, old_expression, new_expression);
    EXECUTE replaced_definition;
  END LOOP;
END;
$migration$;
